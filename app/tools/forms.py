"""Google Forms: create a form and read its responses."""

from app.integrations.google import google
from app.tools.registry import registry
from app.tools.sheets import file_id

API = "https://forms.googleapis.com/v1/forms"


def question_item(q: dict, index: int) -> dict:
    """Turn a simple question description into a Forms API createItem request."""
    kind = q.get("type", "text")
    question: dict = {"required": bool(q.get("required", False))}
    if kind in ("choice", "checkbox", "dropdown"):
        question["choiceQuestion"] = {
            "type": {"choice": "RADIO", "checkbox": "CHECKBOX", "dropdown": "DROP_DOWN"}[kind],
            "options": [{"value": o} for o in q.get("options", [])] or [{"value": "Option 1"}],
        }
    elif kind == "scale":
        question["scaleQuestion"] = {"low": 1, "high": int(q.get("max", 5))}
    else:
        question["textQuestion"] = {"paragraph": kind == "paragraph"}
    return {
        "createItem": {
            "item": {"title": q["title"], "questionItem": {"question": question}},
            "location": {"index": index},
        }
    }


@registry.register(
    "forms_create",
    "Create a Google Form with questions. Returns the link to share and the edit link.",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "type": {"type": "string", "enum": ["text", "paragraph", "choice", "checkbox", "dropdown", "scale"]},
                        "options": {"type": "array", "items": {"type": "string"}},
                        "required": {"type": "boolean"},
                        "max": {"type": "integer", "description": "Top of the scale for 'scale' questions."},
                    },
                    "required": ["title"],
                },
            },
        },
        "required": ["title", "questions"],
    },
)
async def forms_create(title: str, questions: list[dict], description: str = "") -> dict:
    form = await google.post(API, json={"info": {"title": title, "documentTitle": title}})
    requests = [question_item(q, i) for i, q in enumerate(questions)]
    if description:
        requests.insert(
            0,
            {"updateFormInfo": {"info": {"description": description}, "updateMask": "description"}},
        )
    if requests:
        await google.post(f"{API}/{form['formId']}:batchUpdate", json={"requests": requests})
    return {
        "form_id": form["formId"],
        "share_link": form["responderUri"],
        "edit_link": f"https://docs.google.com/forms/d/{form['formId']}/edit",
    }


@registry.register(
    "forms_get_responses",
    "Read the responses to one of the owner's Google Forms.",
    {
        "type": "object",
        "properties": {"form": {"type": "string", "description": "Form id or URL."}},
        "required": ["form"],
    },
)
async def forms_get_responses(form: str) -> dict:
    fid = file_id(form)
    meta = await google.get(f"{API}/{fid}")
    titles = {
        item["questionItem"]["question"]["questionId"]: item["title"]
        for item in meta.get("items", [])
        if "questionItem" in item
    }
    res = await google.get(f"{API}/{fid}/responses")
    responses = []
    for r in res.get("responses", [])[:200]:
        answers = {}
        for qid, a in r.get("answers", {}).items():
            values = [v.get("value", "") for v in a.get("textAnswers", {}).get("answers", [])]
            answers[titles.get(qid, qid)] = ", ".join(values)
        responses.append({"submitted": r.get("lastSubmittedTime"), "answers": answers})
    return {"title": meta["info"]["title"], "count": len(res.get("responses", [])), "responses": responses}

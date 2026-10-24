"""Tools for self-learning: lessons (corrections) and skills (reusable instructions)."""

from app.memory import learning
from app.tools.registry import registry


@registry.register(
    "save_lesson",
    "Save a lesson when the owner corrects you or states how things should be done from now on. "
    "Write it as one short, general rule for the future, e.g. 'Sign work emails as Andrew, not Andy.' "
    "Lessons are added to every future request.",
    {"type": "object", "properties": {"lesson": {"type": "string"}}, "required": ["lesson"]},
)
async def save_lesson(lesson: str) -> dict:
    return {"status": await learning.save_lesson(lesson)}


@registry.register("list_lessons", "List all active lessons with their ids.")
async def list_lessons() -> dict:
    return {"lessons": [{"id": r["id"], "lesson": r["content"]} for r in await learning.list_lessons()]}


@registry.register(
    "forget_lesson",
    "Remove a lesson the owner says is wrong or no longer applies. Use list_lessons to find the id.",
    {"type": "object", "properties": {"lesson_id": {"type": "integer"}}, "required": ["lesson_id"]},
)
async def forget_lesson(lesson_id: int) -> dict:
    return {"status": "forgotten" if await learning.forget_lesson(lesson_id) else "not found"}


@registry.register(
    "create_skill",
    "Save (or update) a skill: step-by-step instructions for a task the owner will ask for again. "
    "Create one on your own when the owner explains how they want a recurring task done, or after you "
    "worked out a multi-step procedure worth reusing. Calling it with an existing name updates that skill.",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short, e.g. 'publish-video' or 'weekly-expenses'."},
            "description": {"type": "string", "description": "One line: when to use this skill."},
            "instructions": {
                "type": "string",
                "description": "Numbered steps with the exact tools, ids, formats and preferences to use.",
            },
        },
        "required": ["name", "description", "instructions"],
    },
)
async def create_skill(name: str, description: str, instructions: str) -> dict:
    status = await learning.save_skill(name, description, instructions)
    return {"status": status, "name": learning.skill_slug(name)}


@registry.register(
    "load_skill",
    "Load the full instructions of a skill from your skills list before doing that task.",
    {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
)
async def load_skill(name: str) -> dict:
    skill = await learning.get_skill(name)
    if not skill:
        return {"error": f"No skill called '{name}'."}
    return {"name": skill["name"], "description": skill["description"], "instructions": skill["instructions"]}


@registry.register(
    "delete_skill",
    "Delete a skill the owner no longer wants.",
    {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
)
async def delete_skill(name: str) -> dict:
    return {"status": "deleted" if await learning.delete_skill(name) else "not found"}

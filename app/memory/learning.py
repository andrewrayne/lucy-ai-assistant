"""Self-learning: lessons from the owner's corrections, and reusable skills.

- lessons: short rules ("Never use emoji in work emails"), injected into every request
- skills:  named step-by-step instructions for recurring tasks; the model sees the
           list (name + description) and loads the full instructions when needed
"""

import re
from datetime import UTC, datetime, timedelta

from postgrest.types import ReturnMethod

from app.memory.db import db

MAX_LESSONS = 50


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9а-яіїєґ ]", "", text.lower()).strip()


def skill_slug(name: str) -> str:
    """'Publish a Video!' -> 'publish-a-video'."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


# ---------- lessons ----------


async def save_lesson(content: str) -> str:
    content = content.strip()
    client = await db()
    existing = (await client.table("lessons").select("id, content").eq("active", True).execute()).data
    if any(_norm(row["content"]) == _norm(content) for row in existing):
        return "already known"
    await client.table("lessons").insert({"content": content}, returning=ReturnMethod.minimal).execute()
    return "saved"


async def list_lessons() -> list[dict]:
    res = await (
        (await db())
        .table("lessons")
        .select("id, content, created_at")
        .eq("active", True)
        .order("created_at")
        .limit(MAX_LESSONS)
        .execute()
    )
    return res.data


async def forget_lesson(lesson_id: int) -> bool:
    res = await (
        (await db()).table("lessons").update({"active": False}).eq("id", lesson_id).eq("active", True).execute()
    )
    return bool(res.data)


# ---------- skills ----------


async def save_skill(name: str, description: str, instructions: str) -> str:
    """Create a skill, or replace the instructions of an existing one with the same name."""
    slug = skill_slug(name)
    if not slug:
        raise ValueError("A skill needs a name.")
    client = await db()
    existing = (await client.table("skills").select("id").eq("name", slug).execute()).data
    row = {"name": slug, "description": description.strip(), "instructions": instructions.strip()}
    if existing:
        row["updated_at"] = datetime.now(UTC).isoformat()
        await client.table("skills").update(row, returning=ReturnMethod.minimal).eq("id", existing[0]["id"]).execute()
        return "updated"
    await client.table("skills").insert(row, returning=ReturnMethod.minimal).execute()
    return "created"


async def list_skills() -> list[dict]:
    res = await (await db()).table("skills").select("name, description, updated_at").order("name").execute()
    return res.data


async def get_skill(name: str) -> dict | None:
    rows = (await (await db()).table("skills").select("*").eq("name", skill_slug(name)).execute()).data
    return rows[0] if rows else None


async def delete_skill(name: str) -> bool:
    res = await (await db()).table("skills").delete().eq("name", skill_slug(name)).execute()
    return bool(res.data)


async def skills_changed_since(days: int = 7) -> list[dict]:
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    res = await (await db()).table("skills").select("name, description").gte("updated_at", since).execute()
    return res.data

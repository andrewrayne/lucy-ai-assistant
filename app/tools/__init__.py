"""Importing this package registers every tool in the shared registry."""

from app.tools import (  # noqa: F401
    agents,
    basics,
    calendar,
    documents,
    drive,
    forms,
    github,
    gmail,
    images,
    learning,
    mac,
    memory,
    news,
    notion,
    phone,
    reminders,
    research,
    sheets,
    weather,
    youtube,
)
from app.tools.registry import registry

__all__ = ["registry"]

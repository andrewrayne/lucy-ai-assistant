"""Background jobs (APScheduler, inside the single Railway replica).

Jobs keep their state in Supabase, never only in process memory, so a
redeploy at any moment loses nothing:
- every minute: send due reminders and the morning brief (reminders table)
- every minute: alert the owner about failed or stuck agent runs (agent_runs table)
- every hour: summarize finished days of conversation (messages table)
- every hour: make sure today's database backup exists in Google Drive
"""

import logging
from datetime import datetime, timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app import agents, owner
from app.config import get_settings
from app.scheduler import reminders
from app.scheduler.backup import ensure_daily_backup
from app.scheduler.brief import ensure_morning_brief
from app.scheduler.daily_summary import summarize_past_days

log = logging.getLogger(__name__)


async def _run_daily_summary() -> None:
    try:
        days = await summarize_past_days()
        if days:
            log.info("Daily summary: %d day(s) summarized", days)
    except Exception:
        log.exception("Daily summary job failed")


async def _run_agent_alerts(bot: Bot) -> None:
    try:
        sent = await agents.alert_problems(bot, get_settings().owner_telegram_id)
        if sent:
            log.info("Sent %d agent alert(s)", sent)
    except Exception:
        log.exception("Agent alert job failed")


async def _run_backup() -> None:
    try:
        await ensure_daily_backup()
    except Exception:
        log.exception("Backup job failed")


async def _run_reminders(bot: Bot) -> None:
    try:
        sent = await reminders.deliver_due(bot)
        if sent:
            log.info("Delivered %d reminder(s)", sent)
    except Exception:
        log.exception("Reminder job failed")


async def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    await owner.load()
    try:
        await ensure_morning_brief()
    except Exception:
        log.exception("Could not schedule the morning brief")

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _run_reminders, "interval", minutes=1, args=[bot], next_run_time=datetime.now() + timedelta(seconds=10),
        id="reminders", max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _run_agent_alerts, "interval", minutes=1, args=[bot], next_run_time=datetime.now() + timedelta(seconds=20),
        id="agent_alerts", max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _run_backup, "interval", hours=1, next_run_time=datetime.now() + timedelta(minutes=2),
        id="backup", max_instances=1, coalesce=True,
    )
    # Hourly is enough: it catches up on any finished day, even after downtime.
    scheduler.add_job(
        _run_daily_summary, "interval", hours=1, next_run_time=datetime.now() + timedelta(seconds=60),
        id="daily_summary", max_instances=1, coalesce=True,
    )
    scheduler.start()
    return scheduler

"""FastAPI server: Telegram webhook + health check."""

import asyncio
import logging
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, MenuButtonWebApp, Update, WebAppInfo
from fastapi import FastAPI, Header, HTTPException, Request

from app import alerts, costs
from app.bot import outbox
from app.bot.handlers import router
from app.bot.owner_only import OwnerOnlyMiddleware
from app.config import get_settings
from app.scheduler.jobs import start_scheduler
from app.web.agents_api import router as agents_router
from app.web.call import router as call_router
from app.web.pages import router as pages_router
from app.web.phone import router as phone_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

settings = get_settings()
bot = Bot(token=settings.telegram_bot_token)
dp = Dispatcher()
dp.update.outer_middleware(OwnerOnlyMiddleware(settings.owner_telegram_id))
dp.include_router(router)
outbox.set_bot(bot)  # lets tools send files and photos to the owner

# Keeps references to running update tasks so they aren't garbage-collected.
_background: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(_: FastAPI):
    alerts.install()  # errors in the log also reach the owner's Telegram
    await costs.load_today()  # the daily limit survives redeploys
    if settings.base_url:
        url = settings.base_url + settings.webhook_path
        await bot.set_webhook(
            url,
            secret_token=settings.webhook_secret,
            allowed_updates=dp.resolve_used_update_types(),
        )
        log.info("Webhook set to %s", url)
        await bot.set_my_commands(
            [
                BotCommand(command="call", description="Call Lucy (voice)"),
                BotCommand(command="new", description="Start a fresh conversation"),
                BotCommand(command="brief", description="Get the morning brief now"),
                BotCommand(command="news", description="Today's AI & tech news"),
                BotCommand(command="city", description="Set your current city, e.g. /city Berlin"),
                BotCommand(command="agents", description="How my AI agents are doing"),
                BotCommand(command="lessons", description="Lessons I've learned from you"),
                BotCommand(command="skills", description="Skills I've saved"),
                BotCommand(command="usage", description="What I've spent today and this month"),
            ]
        )
        # The chat's menu button opens the call (Telegram Mini App), only in the owner's chat.
        await bot.set_chat_menu_button(
            chat_id=settings.owner_telegram_id,
            menu_button=MenuButtonWebApp(text="📞 Call", web_app=WebAppInfo(url=settings.base_url + "/call")),
        )
    else:
        log.warning("No PUBLIC_URL or RAILWAY_PUBLIC_DOMAIN: webhook not set")

    scheduler = await start_scheduler(bot) if settings.supabase_url else None
    yield
    if scheduler:
        scheduler.shutdown(wait=False)
    # We deliberately do not delete the webhook on shutdown: during a
    # redeploy the new instance has already registered it.
    await bot.session.close()


app = FastAPI(title="Personal Assistant", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(pages_router)
app.include_router(agents_router)
app.include_router(call_router)
app.include_router(phone_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post(settings.webhook_path)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    if x_telegram_bot_api_secret_token != settings.webhook_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    update = Update.model_validate(await request.json(), context={"bot": bot})
    # Answer Telegram right away and do the work in the background; otherwise a
    # slow Gemini reply makes Telegram time out and resend the same update.
    task = asyncio.create_task(dp.feed_update(bot, update))
    _background.add(task)
    task.add_done_callback(_background.discard)
    return {"ok": True}

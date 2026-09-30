"""
Free OTP Telegram Bot — entry point.

Run:  BOT_TOKEN=123:ABC python bot.py
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import handlers
import scrapers
from config import BOT_TOKEN, PORT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)   # one line per HTTP request is too noisy
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("bot")


async def _start_health_server(port: int):
    """Tiny HTTP server so web-only free hosts see an open port."""
    from aiohttp import web

    async def ok(_request):
        return web.Response(text="OK")

    app = web.Application()
    app.router.add_get("/", ok)
    app.router.add_get("/health", ok)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("Health server listening on :%s", port)
    return runner


async def _delayed_warmup() -> None:
    await asyncio.sleep(10)                       # let the bot come up first
    await scrapers.warm_up_loop()


async def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN.startswith("PASTE_"):
        raise SystemExit(
            "❌ BOT_TOKEN is not set.\n"
            "   1. Talk to @BotFather -> /newbot -> copy the token\n"
            "   2. Run:  BOT_TOKEN=your_token python bot.py\n"
            "   (or put it in config.py)"
        )

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(handlers.router)

    runner = await _start_health_server(PORT) if PORT else None
    warm = None
    log.info("Starting polling…")
    try:
        # a leftover webhook would make polling fail with "Conflict"
        await bot.delete_webhook(drop_pending_updates=True)
        from aiogram.types import BotCommand
        await bot.set_my_commands([
            BotCommand(command="start", description="Main menu"),
            BotCommand(command="live", description="Live traffic - newest SMS right now"),
            BotCommand(command="country", description="Find a country: /country sweden"),
            BotCommand(command="active", description="Numbers being watched"),
            BotCommand(command="stopall", description="Stop all watchers"),
            BotCommand(command="history", description="Recent SMS"),
            BotCommand(command="lang", description="Language / ভাষা"),
            BotCommand(command="help", description="Help"),
        ])
        me = await bot.get_me()
        log.info("Logged in as @%s", me.username)
        warm = asyncio.create_task(_delayed_warmup(), name="warmup")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        if warm:
            warm.cancel()
        handlers.manager.stop_all()
        await scrapers.close_all()
        if runner:
            await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        if isinstance(e, SystemExit) and e.code not in (None, 0):
            raise

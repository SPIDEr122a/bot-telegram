"""
وب = پروسه اصلی (Railway health check)
ربات = thread جدا

Start Command:
  python run_all.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("run_all")


def _port() -> int:
    return int(os.environ.get("PORT") or "8000")


def _run_bot_thread() -> None:
    async def _bot() -> None:
        await asyncio.sleep(1)
        try:
            import config
            import database as db
            import bot as bot_module

            if not config.BOT_TOKEN:
                logger.error("BOT_TOKEN empty — skip bot")
                return

            await db.init_db()
            await bot_module.bot.delete_webhook(drop_pending_updates=True)
            me = await bot_module.bot.get_me()
            bot_module.BOT_USERNAME = me.username or ""
            if bot_module.BOT_USERNAME:
                os.environ["BOT_USERNAME"] = bot_module.BOT_USERNAME
            logger.info("Bot OK @%s", bot_module.BOT_USERNAME)
            await bot_module.dp.start_polling(bot_module.bot)
        except Exception:
            logger.exception("Bot died — web still up")

    try:
        asyncio.run(_bot())
    except Exception:
        logger.exception("Bot thread failed")


def main() -> None:
    port = _port()
    logger.info("PORT=%s — binding 0.0.0.0:%s", port, port)

    t = threading.Thread(target=_run_bot_thread, name="telegram-bot", daemon=True)
    t.start()

    import uvicorn

    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="*",
        workers=1,
    )


if __name__ == "__main__":
    main()

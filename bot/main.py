import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
import httpx

from .config import BOT_TOKEN, LOCAL_API_URL, USE_LOCAL_API
from .handlers import router


async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    
    # Session dengan timeout besar untuk film ukuran besar
    session = AiohttpSession(timeout=httpx.Timeout(3600, connect=30))
    
    base_url = f"{LOCAL_API_URL}/bot{BOT_TOKEN}" if USE_LOCAL_API else None
    bot = Bot(token=BOT_TOKEN, session=session, base_url=base_url)
    
    dp = Dispatcher()
    dp.include_router(router)
    
    logging.info("Bot thumbnail film berjalan...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

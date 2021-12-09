import asyncio
import logging

from config import config
from settings import settings
from bot import MusicBot

logger = logging.getLogger(settings.app_name)


if __name__ == "__main__":
    logger.info("Start app")
    settings.restart = True
    while settings.restart:
        settings.restart = False
        bot = MusicBot(settings.command_prefix, loop=asyncio.new_event_loop())
        bot.run(config.tokens.get("discord"))

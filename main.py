import asyncio
import logging

import discord

from bot import MusicBot
from config import config
from settings import settings

logger = logging.getLogger(settings.app_name)


if __name__ == "__main__":
    logger.info("Start app")
    settings.restart = True
    while settings.restart:
        settings.restart = False
        bot = MusicBot(settings.command_prefix, loop=asyncio.new_event_loop(), intents=discord.Intents.all())
        bot.run(config.tokens.get("discord", ""))

import logging

from config import config
from settings import settings
from bot import MusicBot

logger = logging.getLogger(settings.app_name)


if __name__ == "__main__":
    logger.info("Start app")
    bot = MusicBot(settings.command_prefix)
    bot.run(config.tokens.get("discord"))

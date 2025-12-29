import discord
from discord.ext.commands import Bot

from bot.cogs.music import MusicCog
from bot.cogs.system import SystemCog
from bot.factory import ServiceFactory
from config.settings import Settings
from core.logging import logger

if __name__ == "__main__":
    logger.info("Start app")
    settings = Settings()
    settings.restart = True

    while settings.restart:
        settings.restart = False
        bot = Bot(
            command_prefix=settings.command_prefix,
            intents=discord.Intents.all(),
        )

        @bot.event
        async def setup_hook(bot: Bot = bot) -> None:
            await bot.add_cog(
                MusicCog(
                    bot=bot,
                    service_factory=ServiceFactory(settings=settings),
                    settings=settings,
                )
            )
            await bot.add_cog(SystemCog(bot=bot, settings=settings, service_factory=ServiceFactory(settings=settings)))

        bot.run(settings.tokens.get("discord", ""))

import logging
from collections.abc import Generator
from datetime import timedelta
from enum import Enum

from dateutil import parser
from discord import Colour, Embed
from discord.ext.commands import Context

from settings import settings

logger = logging.getLogger(settings.app_name)


class SearchDomains(str, Enum):
    youtube = "www.youtube.com"
    youtube_short = "youtu.be"
    yandex_music = "music.yandex"
    spotify = "open.spotify.com"


async def send_message(ctx: Context, message: str, level: int = logging.INFO) -> None:
    embed = Embed(title=message if len(message) <= 256 else f"{message[:253]}...")
    if level == logging.INFO:
        logger.info(message)
        embed.colour = Colour.blue()
    elif level == logging.WARNING:
        logger.warning(message)
        embed.colour = Colour.from_rgb(255, 255, 0)
    elif level == logging.ERROR:
        logger.error(message)
        embed.colour = Colour.red()
    await ctx.send(embed=embed)


def parse_play_args(args: tuple[str, ...]) -> tuple[str, timedelta]:
    start_time = timedelta()
    strings = list(args)
    if len(args) > 1:
        try:
            parsed_time = parser.parse(strings[-1])
            start_time = timedelta(seconds=parsed_time.second, hours=parsed_time.hour, minutes=parsed_time.minute)
            strings.pop()
        except ValueError:
            pass

    source = " ".join(strings)
    return source, start_time


def chunks(lst: list, n: int) -> Generator:
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i : i + n]

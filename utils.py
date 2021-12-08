import logging
from datetime import datetime
from enum import Enum
from typing import Tuple, Optional

from dateutil import parser
from discord import Embed, Colour
from discord.ext.commands import Context

from settings import settings

logger = logging.getLogger(settings.app_name)


class SearchDomains(Enum):
    youtube = "www.youtube.com"
    yandex_music = "music.yandex.by"


async def send_message(ctx: Context, message: str, level: int = logging.INFO):
    embed = Embed(title=message)
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


def parse_play_args(args: tuple[str]) -> Tuple[str, Optional[datetime], SearchDomains]:
    start_time = None
    search_source = SearchDomains.youtube
    strings = list(args)
    if len(args) > 1:
        try:
            start_time = parser.parse(strings[-1])
            strings.pop()
        except ValueError:
            pass
        search_source_str = strings[-1]
        if search_source_str in ("yt", "ym"):
            if search_source_str == "yt":
                search_source = SearchDomains.youtube
            elif search_source_str == "ym":
                search_source = SearchDomains.yandex_music
            strings.pop()

    source = " ".join(strings)
    return source, start_time, search_source


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

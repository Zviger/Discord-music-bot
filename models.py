import datetime
from asyncio import Future
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from dateutil import parser


@dataclass
class UserSettings:
    gratings_text: str = ""
    gratings_image_name: str = ""


@dataclass
class Track:
    id: str
    title: str
    link: str
    duration: int
    uuid: UUID
    start_time: datetime.datetime = parser.parse("00:00:00")
    im_start_time: datetime.datetime = parser.parse("00:00:00")
    is_stream: bool = False
    is_twitch: bool = False
    download_task: Optional[Future] = None

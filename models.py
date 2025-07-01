import datetime
from asyncio import Future
from dataclasses import dataclass
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
    stream_link: str | None = None
    download_task: Future | None = None

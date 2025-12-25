from asyncio import Future
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID


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
    start_time: timedelta = timedelta()
    im_start_time: timedelta = timedelta()
    stream_link: str | None = None
    download_task: Future | None = None

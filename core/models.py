from asyncio import Future
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID


@dataclass
class UserSettings:
    gratings_text: str = ""
    gratings_image_name: str = ""

@dataclass
class AutoReply:
    text: str
    image_name: str

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
    file_extension: str | None = None


@dataclass
class TrackInfo:
    is_current: bool
    played_time: timedelta
    full_time: timedelta
    is_stream: bool
    is_interrupting: bool
    title: str
    download_done: bool
    queue_index: int = 0

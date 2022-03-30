import datetime
from dataclasses import dataclass

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
    length: int
    creation_time: float
    start_time: datetime.datetime = parser.parse("00:00:00")
    im_start_time: datetime.datetime = parser.parse("00:00:00")

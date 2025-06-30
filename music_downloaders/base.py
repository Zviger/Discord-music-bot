from abc import ABC, abstractmethod

from models import Track


class MusicDownloader(ABC):
    @abstractmethod
    async def download(
        self,
        source: str,
        butch_download_allowed: bool = True,
        force_load_first: bool = False,
    ) -> list[Track]:
        pass

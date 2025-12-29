from abc import ABC, abstractmethod

from core.models import Track


class MusicDownloader(ABC):
    @abstractmethod
    async def download(
        self,
        source: str,
        *,
        only_one: bool = True,
        force_load_first: bool = False,
    ) -> list[Track]:
        pass

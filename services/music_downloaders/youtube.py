import asyncio
import itertools
import time
import uuid
from collections.abc import Callable, Generator, Iterable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

import yt_dlp as youtube_dl

from core.exceptions import CantDownloadError
from core.logging import logger
from core.models import Track
from services.music_downloaders.base import MusicDownloader


class Executor:
    def __init__(self, loop: asyncio.AbstractEventLoop, thread_count: int = 1) -> None:
        self._ex = ThreadPoolExecutor(max_workers=thread_count)
        self._loop = loop

    def __call__(self, f: Callable, *args: Any, **kwargs: Any) -> asyncio.Future:  # noqa: ANN401
        return self._loop.run_in_executor(self._ex, partial(f, *args, **kwargs))


class YtLogger:
    _IGNORED_WARNINGS = [
        "SABR streaming",
        "web client https formats have been skipped",
        "missing a url",
        "No supported JavaScript runtime could be found.",
    ]

    @staticmethod
    def debug(msg: str) -> None:
        logger.debug(msg)

    @staticmethod
    def warning(msg: str) -> None:
        if any(ignored in msg for ignored in YtLogger._IGNORED_WARNINGS):
            logger.debug("yt-dlp: %s", msg)
        else:
            logger.warning(msg)

    @staticmethod
    def error(msg: str) -> None:
        logger.error(msg)


class YouTubeDownloader(MusicDownloader):
    FILE_EXTENSION = ".opus"

    def __init__(self, cache_dir: Path) -> None:
        self._client = youtube_dl.YoutubeDL(
            params={
                "format": "bestaudio/best",
                "outtmpl": f"{cache_dir}/%(id)s.%(ext)s",
                "skip-unavailable-fragments": True,
                "youtube-skip-dash-manifest": True,
                "cache-dir": "~/.cache/youtube-dl",
                "logger": YtLogger,
                "default_search": "auto",
                "quiet": True,
                "no_warnings": True,
                "nopart": True,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "opus",
                        "preferredquality": "192",
                    },
                ],
            },
        )
        self._download_thread_count = 8
        self._cache_dir = cache_dir

    async def download(
        self,
        source: str,
        *,
        only_one: bool = True,
        force_load_first: bool = False,
    ) -> list[Track]:
        tracks = []

        source_info = self._client.extract_info(source, download=False, process=False)

        if (
            source_info is not None
            and "youtu" in source_info["extractor"]
            and source_info.get("live_status") != "is_live"
        ):
            if entries := source_info.get("entries"):
                entries = list(itertools.islice(entries, 50))

                if only_one:
                    entries = [entries[0]]

                tracks.extend(await self._batch_download(source_infos=entries, force_load_first=force_load_first))
            else:
                tracks.append(await self._download(source_info))
        else:
            source_info = self._client.extract_info(source, download=False)

            if source_info is not None:
                if source_info.get("is_live"):
                    tracks.append(
                        Track(
                            id=source_info["id"],
                            title=source_info["title"].strip(),
                            link=source_info["original_url"].strip(),
                            duration=0,
                            stream_link=source_info["url"],
                            uuid=uuid.uuid4(),
                        ),
                    )
                else:
                    tracks.append(await self._download(source_info["entries"][0]))

        if not tracks:
            msg = "Can't download music by this source"
            raise CantDownloadError(msg)

        return tracks

    async def batch_download_by_track_names(
        self,
        track_names: list[str],
        *,
        force_load_first: bool = False,
    ) -> list[Track]:
        source_infos = []
        for track_name in track_names:
            source_info = self._client.extract_info(track_name, download=False)

            if source_info is not None:
                source_infos.append(source_info["entries"][0])

        return await self._batch_download(source_infos=source_infos, force_load_first=force_load_first)

    async def _download(self, source_info: dict) -> Track:
        file_path = self._cache_dir / f"{source_info['id']}{self.FILE_EXTENSION}"
        if not file_path.exists():
            self.__download_from_client(source_info["original_url"])

        return Track(
            id=source_info["id"],
            title=source_info["title"].strip(),
            link=source_info["original_url"].strip(),
            duration=source_info["duration"],
            uuid=uuid.uuid4(),
            file_extension=self.FILE_EXTENSION,
        )

    async def _batch_download(self, source_infos: list[dict], *, force_load_first: bool) -> list[Track]:
        tracks = []
        executor = Executor(thread_count=self._download_thread_count, loop=asyncio.get_event_loop())

        if force_load_first:
            for source_info in source_infos[:2]:
                url = source_info.get("webpage_url") or source_info["url"]

                self.__download_from_client(url)
                tracks.append(
                    Track(
                        id=source_info["id"],
                        title=source_info["title"].strip(),
                        link=url.strip(),
                        duration=source_info["duration"],
                        uuid=uuid.uuid4(),
                        file_extension=self.FILE_EXTENSION,
                    ),
                )

            source_infos = source_infos[2:]

        for chunk in self._chunks(source_infos, len(source_infos) // self._download_thread_count + 1):
            download_task = executor(
                self.__batch_sync_download,
                urls=(i.get("webpage_url") or i["url"] for i in chunk),
            )
            for source_info in chunk:
                url = source_info.get("webpage_url") or source_info["url"]
                tracks.append(
                    Track(
                        id=source_info["id"],
                        title=source_info["title"].strip(),
                        link=url.strip(),
                        duration=source_info["duration"],
                        uuid=uuid.uuid4(),
                        download_task=download_task,
                        file_extension=self.FILE_EXTENSION,
                    ),
                )

        return tracks

    def _chunks(self, lst: list, n: int) -> Generator:
        for i in range(0, len(lst), n):
            yield lst[i : i + n]

    def __batch_sync_download(self, urls: Iterable[str]) -> None:
        for url in urls:
            self.__download_from_client(url)

    def __download_from_client(self, url: str) -> None:
        while True:
            try:
                self._client.download(url)
            except youtube_dl.utils.DownloadError as e:
                if "HTTP Error 416" in str(e):
                    file_id = url.split("=")[-1]
                    file_path = self._cache_dir / f"{file_id}{self.FILE_EXTENSION}"
                    if file_path.exists():
                        file_path.unlink()
                else:
                    time.sleep(5)
                    continue
            else:
                break

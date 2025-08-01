import asyncio
import logging
import os
import time
import uuid
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

import yt_dlp as youtube_dl

from exceptions import BatchDownloadNotAllowed, CantDownloadException
from models import Track
from music_downloaders.base import MusicDownloader
from utils import chunks

logger = logging.getLogger(__name__)


class Executor:
    def __init__(self, loop: asyncio.AbstractEventLoop, thread_count: int = 1):
        self._ex = ThreadPoolExecutor(max_workers=thread_count)
        self._loop = loop

    def __call__(self, f, *args, **kwargs):
        return self._loop.run_in_executor(self._ex, partial(f, *args, **kwargs))


class YtLogger:
    @staticmethod
    def debug(msg) -> None:
        logger.debug(msg)

    @staticmethod
    def warning(msg) -> None:
        logger.warning(msg)

    @staticmethod
    def error(msg) -> None:
        logger.error(msg)


class YouTubeDownloader(MusicDownloader):
    def __init__(self, cache_dir: str) -> None:
        self._client = youtube_dl.YoutubeDL(
            params={
                "format": "bestaudio/best",
                "outtmpl": f"{cache_dir}/%(id)s",
                # "ignoreerrors": True,
                "skip-unavailable-fragments": True,
                "youtube-skip-dash-manifest": True,
                "cache-dir": "~/.cache/youtube-dl",
                "logger": YtLogger,
                "default_search": "auto",
                "quiet": True,
                "no_warnings": True,
                "nopart": True,
            },
        )
        self._download_thread_count = 8
        self._cache_dir = cache_dir

    async def download(
        self,
        source: str,
        batch_download_allowed: bool = True,
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
                if not batch_download_allowed:
                    raise BatchDownloadNotAllowed

                entries = list(entries)[:50]
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
            raise CantDownloadException("Can't download music by this source")

        return tracks

    async def batch_download_by_track_names(
        self,
        track_names: list[str],
        force_load_first: bool = False,
    ) -> list[Track]:
        source_infos = []
        for track_name in track_names:
            source_info = self._client.extract_info(track_name, download=False)

            if source_info is not None:
                source_infos.append(source_info["entries"][0])

        return await self._batch_download(source_infos=source_infos, force_load_first=force_load_first)

    async def _download(self, source_info: dict) -> Track:
        if not Path(f"{self._cache_dir}/{source_info['id']}").exists():
            self.__download_from_client(source_info["original_url"])

        return Track(
            id=source_info["id"],
            title=source_info["title"].strip(),
            link=source_info["original_url"].strip(),
            duration=source_info["duration"],
            uuid=uuid.uuid4(),
        )

    async def _batch_download(self, source_infos: list[dict], force_load_first: bool) -> list[Track]:
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
                    ),
                )

            source_infos = source_infos[2:]

        for chunk in chunks(source_infos, len(source_infos) // self._download_thread_count + 1):
            download_task = executor(
                self.__batch_sync_download,
                urls=map(lambda i: i.get("webpage_url") or i["url"], chunk),
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
                    ),
                )

        return tracks

    def __batch_sync_download(self, urls: Iterable[str]) -> None:
        for url in urls:
            self.__download_from_client(url)

    def __download_from_client(self, url: str) -> None:
        while True:
            try:
                self._client.download(url)
            except youtube_dl.utils.DownloadError as e:
                if "HTTP Error 416" in str(e):
                    file_path = f"{self._cache_dir}/{url.split("=")[-1]}"

                    if os.path.exists(file_path):
                        os.remove(file_path)
                else:
                    time.sleep(5)
                    continue
            else:
                break

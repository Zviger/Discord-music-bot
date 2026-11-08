import asyncio
import itertools
import shutil
import subprocess
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
        if "Video unavailable" in msg:
            logger.warning(msg.removeprefix("ERROR: ").strip())
            return

        logger.error(msg)


def _node_version(path: Path) -> tuple[int, ...] | None:
    try:
        completed = subprocess.run(  # noqa: S603
            [path, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    parts: list[int] = []
    for part in completed.stdout.strip().removeprefix("v").split("."):
        if not part.isdigit():
            break
        parts.append(int(part))

    return tuple(parts) or None


def _node_runtime_config() -> dict[str, dict[str, str]]:
    """yt-dlp can solve YouTube's JS challenge only with Node.js 22+."""
    candidates: list[Path] = []
    found = shutil.which("node")
    if found:
        candidates.append(Path(found))

    nvm_root = Path.home() / ".nvm" / "versions" / "node"
    if nvm_root.is_dir():
        candidates.extend(nvm_root.glob("*/bin/node"))

    best_path: Path | None = None
    best_version: tuple[int, ...] = ()
    for candidate in candidates:
        if not candidate.is_file():
            continue
        version = _node_version(candidate)
        if version is None or version < (22, 0, 0) or version <= best_version:
            continue
        best_path = candidate
        best_version = version

    if best_path is None:
        logger.warning("Node.js 22+ was not found. YouTube downloads may be blocked.")
        return {"node": {}}

    return {"node": {"path": str(best_path)}}


class YouTubeDownloader(MusicDownloader):
    FILE_EXTENSION = ".webm"
    _KNOWN_EXTENSIONS = (".webm", ".opus", ".m4a", ".mp3", ".ogg")

    def __init__(self, cache_dir: Path) -> None:
        self._client = youtube_dl.YoutubeDL(
            params={
                "format": "bestaudio[ext=webm]/bestaudio/best",
                "outtmpl": f"{cache_dir}/%(id)s.%(ext)s",
                "skip-unavailable-fragments": True,
                "youtube-skip-dash-manifest": True,
                "cache-dir": "~/.cache/youtube-dl",
                "logger": YtLogger,
                "default_search": "auto",
                "quiet": True,
                "no_warnings": True,
                "nopart": True,
                "js_runtimes": _node_runtime_config(),
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

        try:
            source_info = self._extract_info(source)
        except youtube_dl.utils.DownloadError as e:
            msg = str(e).removeprefix("ERROR: ").strip() or "Can't download music by this source"
            raise CantDownloadError(msg) from e

        if (
            source_info is not None
            and "youtu" in source_info["extractor"]
            and source_info.get("live_status") != "is_live"
        ):
            if raw_entries := source_info.get("entries"):
                entries = list(itertools.islice(self._playable_entries(raw_entries), 50))

                if only_one:
                    entries = entries[:1]

                if entries:
                    tracks.extend(await self._batch_download(source_infos=entries, force_load_first=force_load_first))
            else:
                tracks.append(await self._download(source_info))
        else:
            source_info = self._extract_info(source)

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

    def _extract_info(self, source: str) -> dict | None:
        # Unavailable playlist items must not abort the rest of the playlist.
        # Resolving every video here walks the whole list before playback can start.
        self._client.params["ignoreerrors"] = True
        if "list=" in source:
            self._client.params["extract_flat"] = "in_playlist"
        try:
            info = self._client.extract_info(source, download=False, process=True)
        finally:
            self._client.params.pop("ignoreerrors", None)
            self._client.params.pop("extract_flat", None)

        return info if isinstance(info, dict) else None

    def _playable_entries(self, entries: Iterable) -> Generator:
        for entry in entries:
            if not entry or not entry.get("id") or not entry.get("title"):
                continue

            if not (entry.get("webpage_url") or entry.get("url")):
                continue

            yield entry

    async def batch_download_by_track_names(
        self,
        track_names: list[str],
        *,
        force_load_first: bool = False,
    ) -> list[Track]:
        source_infos = []
        for track_name in track_names:
            source_info = self._extract_info(track_name)

            if source_info is not None:
                source_infos.append(source_info["entries"][0])

        return await self._batch_download(source_infos=source_infos, force_load_first=force_load_first)

    def _cached_audio(self, video_id: str) -> Path | None:
        for extension in self._KNOWN_EXTENSIONS:
            file_path = self._cache_dir / f"{video_id}{extension}"
            if file_path.is_file():
                return file_path

        return None

    def _remove_cached_audio(self, video_id: str) -> None:
        for extension in self._KNOWN_EXTENSIONS:
            file_path = self._cache_dir / f"{video_id}{extension}"
            if file_path.is_file():
                file_path.unlink()

    async def _download(self, source_info: dict) -> Track:
        file_path = self._cached_audio(source_info["id"])
        if file_path is None:
            self.__download_from_client(source_info["original_url"], source_info["id"])
            file_path = self._cached_audio(source_info["id"])

        if file_path is None:
            msg = "Can't download music by this source"
            raise CantDownloadError(msg)

        return Track(
            id=source_info["id"],
            title=source_info["title"].strip(),
            link=source_info["original_url"].strip(),
            duration=source_info["duration"],
            uuid=uuid.uuid4(),
            file_extension=file_path.suffix,
        )

    async def _batch_download(self, source_infos: list[dict], *, force_load_first: bool) -> list[Track]:
        tracks = []
        executor = Executor(thread_count=self._download_thread_count, loop=asyncio.get_event_loop())

        if force_load_first:
            ready = source_infos[:2]
            await executor(
                self.__batch_sync_download,
                items=((item.get("webpage_url") or item["url"], item["id"]) for item in ready),
            )
            for source_info in ready:
                url = source_info.get("webpage_url") or source_info["url"]
                tracks.append(
                    Track(
                        id=source_info["id"],
                        title=source_info["title"].strip(),
                        link=url.strip(),
                        duration=int(source_info.get("duration") or 0),
                        uuid=uuid.uuid4(),
                        file_extension=self.FILE_EXTENSION,
                    ),
                )

            source_infos = source_infos[2:]

        for chunk in self._chunks(source_infos, len(source_infos) // self._download_thread_count + 1):
            download_task = executor(
                self.__batch_sync_download,
                items=((i.get("webpage_url") or i["url"], i["id"]) for i in chunk),
            )
            for source_info in chunk:
                url = source_info.get("webpage_url") or source_info["url"]
                tracks.append(
                    Track(
                        id=source_info["id"],
                        title=source_info["title"].strip(),
                        link=url.strip(),
                        duration=int(source_info.get("duration") or 0),
                        uuid=uuid.uuid4(),
                        download_task=download_task,
                        file_extension=self.FILE_EXTENSION,
                    ),
                )

        return tracks

    def _chunks(self, lst: list, n: int) -> Generator:
        for i in range(0, len(lst), n):
            yield lst[i : i + n]

    def __batch_sync_download(self, items: Iterable[tuple[str, str]]) -> None:
        for url, video_id in items:
            self.__download_from_client(url, video_id)

    def __download_from_client(self, url: str, video_id: str) -> None:
        if self._cached_audio(video_id) is not None:
            return

        while True:
            try:
                self._client.download(url)
            except youtube_dl.utils.DownloadError as e:
                message = str(e)
                if "Video unavailable" in message:
                    logger.warning(message.removeprefix("ERROR: ").strip())
                    return

                if "HTTP Error 416" in message:
                    self._remove_cached_audio(video_id)
                else:
                    time.sleep(5)
                    continue
            else:
                break

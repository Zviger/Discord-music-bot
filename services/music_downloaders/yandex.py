import asyncio
import itertools
import uuid
from pathlib import Path
from urllib import parse

import yandex_music
from yandex_music.utils.request_async import Request

from core.exceptions import CantDownloadError
from core.models import Track
from services.music_downloaders.base import MusicDownloader


class YandexMusicDownloader(MusicDownloader):
    def __init__(self, token: str, cache_dir: Path) -> None:
        self._request = Request(timeout=1000)
        self._client = yandex_music.ClientAsync(token=token, request=self._request)
        self._request.set_and_return_client(self._client)
        self._cache_dir = cache_dir

    async def download(
        self,
        source: str,
        *,
        only_one: bool = True,
        force_load_first: bool = False,
    ) -> list[Track]:
        parsed_url = parse.urlparse(source)
        path_args = parsed_url.path.strip("/").split("/")
        tracks = []
        ym_tracks = []

        if len(path_args) == 2 and path_args[0] == "album" and path_args[1].isnumeric():
            album = await self._client.albums_with_tracks(int(path_args[1]))

            if album is not None and album.volumes is not None:
                ym_tracks = list(itertools.chain(*album.volumes))
        elif (
            len(path_args) == 4 and path_args[0] == "users" and path_args[2] == "playlists" and path_args[3].isnumeric()
        ):
            user_login, playlist_id = path_args[1], int(path_args[3])
            playslists = await self._client.users_playlists(playlist_id, user_login)
            playslist = playslists[0] if isinstance(playslists, list) else playslists
            for ym_track_short in playslist.tracks:
                ym_tracks.append(await ym_track_short.fetch_track_async())
        elif (
            len(path_args) == 4
            and path_args[0] == "album"
            and path_args[1].isnumeric()
            and path_args[2] == "track"
            and path_args[3].isnumeric()
        ):
            ym_tracks = await self._client.tracks(f"{path_args[3]}:{path_args[1]}")
        else:
            msg = "Cant download yandex music"
            raise CantDownloadError(msg)

        if len(ym_tracks) > 1 and only_one:
            ym_tracks = [ym_tracks[0]]

        for i, ym_track in enumerate(ym_tracks):
            if not ym_track.available:
                continue

            track = await self._download(ym_track, force_load=force_load_first and i == 0)
            tracks.append(track)

        return tracks

    async def _download(self, track: yandex_music.Track, *, force_load: bool) -> Track:
        download_task = None

        if not (filepath := self._cache_dir.joinpath(track.track_id)).exists():
            download_task = asyncio.create_task(track.download_async(str(filepath)))
            if force_load:
                await download_task

        track_id, album_id = track.track_id.split(":")

        return Track(
            id=track.track_id,
            title=track.title or "",
            link=f"https://music.yandex.by/album/{album_id}/track/{track_id}",
            duration=track.duration_ms // 1000 if track.duration_ms is not None else 0,
            uuid=uuid.uuid4(),
            download_task=download_task,
        )

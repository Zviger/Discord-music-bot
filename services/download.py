from urllib import parse

from core.models import SearchDomains, Track
from services.music_downloaders.yandex import YandexMusicDownloader
from services.music_downloaders.youtube import YouTubeDownloader
from services.music_info_loaders.spotify import SpotifyInfoLoader


class DownloadService:
    def __init__(
        self,
        yt_downloader: YouTubeDownloader,
        ym_downloader: YandexMusicDownloader,
        spotify_loader: SpotifyInfoLoader,
    ) -> None:
        self._yt_downloader = yt_downloader
        self._ym_downloader = ym_downloader
        self._spotify_loader = spotify_loader

    async def download(
        self,
        source: str,
        *,
        only_one: bool = False,
        force_load_first: bool = False,
    ) -> list[Track]:
        parsed_url = parse.urlparse(source)
        netloc = parsed_url.netloc
        tracks = []

        if netloc.startswith(SearchDomains.yandex_music):
            tracks = await self._ym_downloader.download(
                source=source,
                only_one=only_one,
                force_load_first=force_load_first,
            )
        elif netloc.startswith(SearchDomains.spotify):
            track_names = await self._spotify_loader.get_track_names(source=source)

            if only_one and len(track_names) > 1:
                track_names = [track_names[0]]

            tracks = await self._yt_downloader.batch_download_by_track_names(
                track_names=track_names,
                force_load_first=force_load_first,
            )
        else:
            tracks = await self._yt_downloader.download(
                source=source,
                only_one=only_one,
                force_load_first=force_load_first,
            )

        return tracks

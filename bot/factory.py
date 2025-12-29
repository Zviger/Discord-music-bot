from discord import VoiceClient

from config.settings import Settings
from services.download import DownloadService
from services.message import MessageService
from services.music import MusicService
from services.music_downloaders.yandex import YandexMusicDownloader
from services.music_downloaders.youtube import YouTubeDownloader
from services.music_info_loaders.spotify import SpotifyInfoLoader
from services.player import Player
from services.queue import QueueManager


class ServiceFactory:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._message_service: MessageService | None = None

    def create_music_service(
        self,
        voice_client: VoiceClient,
    ) -> MusicService:
        ym_downloader = YandexMusicDownloader(
            token=self.settings.tokens["yandex_music"],
            cache_dir=self.settings.cached_music_dir,
        )
        yt_downloader = YouTubeDownloader(cache_dir=self.settings.cached_music_dir)
        spotify_loader = SpotifyInfoLoader(
            client_id=self.settings.tokens["spotify_client_id"],
            client_secret=self.settings.tokens["spotify_client_secret"],
        )

        download_service = DownloadService(
            yt_downloader=yt_downloader,
            ym_downloader=ym_downloader,
            spotify_loader=spotify_loader,
        )

        queue_manager = QueueManager()
        player = Player(
            voice_client=voice_client,
            settings=self.settings,
        )

        # Create music service
        return MusicService(
            voice_client=voice_client,
            queue_manager=queue_manager,
            player=player,
            download_service=download_service,
            message_service=self.create_message_service(),
            settings=self.settings,
        )

    def create_message_service(self) -> MessageService:
        if self._message_service is None:
            self._message_service = MessageService()

        return self._message_service

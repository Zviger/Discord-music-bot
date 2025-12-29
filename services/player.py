from collections.abc import Callable
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from discord import FFmpegPCMAudio, PCMVolumeTransformer, VoiceClient

from config.settings import Settings
from core.models import Track


class PlayerStatus(Enum):
    PLAYING = 0
    NOT_PLAYING = 1
    PAUSED = 2


class Player:
    def __init__(self, voice_client: VoiceClient, settings: Settings) -> None:
        self._status = PlayerStatus.NOT_PLAYING
        self._voice_client = voice_client
        self._settings = settings

    def is_in_any_status(
        self, *statuses: Literal[PlayerStatus.PLAYING, PlayerStatus.NOT_PLAYING, PlayerStatus.PAUSED]
    ) -> bool:
        return self._status in statuses

    async def try_play(
        self,
        track: Track,
        on_music_end_callback: Callable[[Exception | None], None],
        on_success_play_callback: Callable,
    ) -> None:
        if not self.is_in_any_status(PlayerStatus.PLAYING, PlayerStatus.PAUSED):
            if track.download_task:
                await track.download_task

            track.im_start_time = track.start_time
            start_time = str(track.start_time)
            track.start_time = timedelta()

            audio_kwargs: dict[str, Any] = {
                "options": f"-af bass=g={self._settings.bass_value}",
            }
            if track.stream_link:
                audio_kwargs["source"] = track.stream_link
            else:
                audio_kwargs["source"] = str(Path(self._settings.cached_music_dir).joinpath(track.id))
                audio_kwargs["before_options"] = f"-ss {start_time}"

            self._voice_client.play(
                PCMVolumeTransformer(
                    FFmpegPCMAudio(**audio_kwargs),
                    volume=self._settings.volume_value / 100,
                ),
                after=on_music_end_callback,
            )
            self._status = PlayerStatus.PLAYING

            await on_success_play_callback()

    def stop(self) -> None:
        self._status = PlayerStatus.NOT_PLAYING
        self._voice_client.stop()

    def pause(self) -> None:
        self._status = PlayerStatus.PAUSED
        self._voice_client.pause()

    def resume(self) -> None:
        self._status = PlayerStatus.PLAYING
        self._voice_client.resume()

    def get_played_and_full_time(self, track: Track) -> tuple[timedelta, timedelta]:
        current_time = timedelta(
            seconds=int(
                (self._voice_client._player.loops if self._voice_client._player is not None else 0) * 0.02  # noqa: SLF001
                + track.im_start_time.total_seconds(),
            )
        )
        full_time = timedelta(seconds=track.duration)

        return current_time, full_time

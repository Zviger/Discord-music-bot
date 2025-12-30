import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta

from discord import (
    Activity,
    ActivityType,
    Member,
    Reaction,
    Status,
    User,
    VoiceClient,
)
from discord.ext.commands import Context

from config.settings import Settings
from core.exceptions import CantDownloadError, CantLoadTrackInfoError
from core.logging import logger
from core.models import Track, TrackInfo
from services.download import DownloadService
from services.message import MessageService
from services.player import Player, PlayerStatus
from services.queue import QueueManager

# TODO(@<zviger>): Fix it  # noqa: FIX002, TD003
SLEEP_TIME = 0.25


class MusicService:
    def __init__(  # noqa: PLR0913
        self,
        voice_client: VoiceClient,
        queue_manager: QueueManager,
        player: Player,
        download_service: DownloadService,
        message_service: MessageService,
        settings: Settings,
    ) -> None:
        self._queue_manager = queue_manager
        self._settings = settings
        self._player = player
        self._voice_client = voice_client
        self._download_service = download_service
        self._message_service = message_service

    async def add_to_playlist(
        self,
        source: str,
        ctx: Context,
        start_time: timedelta | None,
    ) -> None:
        tracks = await self._download(
            source=source,
            ctx=ctx,
            start_time=start_time,
        )
        self._queue_manager.add_many(tracks)

    async def play(
        self,
        source: str,
        ctx: Context,
        start_time: timedelta | None,
    ) -> None:
        tracks = await self._download(
            source=source,
            ctx=ctx,
            start_time=start_time,
            force_load_first=True,
        )
        if tracks:
            self._queue_manager.add_many(tracks)

            if not self._player.is_in_any_status(PlayerStatus.PLAYING):
                track = self._queue_manager.get_next()
                if track is not None:
                    await self._player.try_play(
                        track=track,
                        on_success_play_callback=self._on_success_play_callback_factory(ctx=ctx, track=track),
                        on_music_end_callback=self._on_music_end_callback_factory(ctx=ctx),
                    )

    async def im_play(
        self,
        source: str,
        ctx: Context,
        start_time: timedelta,
    ) -> None:
        tracks = await self._download(source, ctx, start_time, is_im_track=True)
        track = tracks[0]

        if self._player.is_in_any_status(PlayerStatus.PLAYING, PlayerStatus.NOT_PLAYING):
            if self._player.is_in_any_status(PlayerStatus.PLAYING):
                current_track = self._queue_manager.get_current()
                if current_track is not None:
                    current_time, _ = self._player.get_played_and_full_time(current_track)
                    current_track.start_time = current_time

                self._player.stop()
                await asyncio.sleep(SLEEP_TIME)

            self._queue_manager.add_interruption(track)
            await self._player.try_play(
                track=track,
                on_success_play_callback=self._on_success_play_callback_factory(ctx=ctx, track=track),
                on_music_end_callback=self._on_music_end_callback_factory(ctx=ctx),
            )
        elif self._player.is_in_any_status(PlayerStatus.PAUSED):
            await self._message_service.send(ctx, "Music shouldn't be paused!", logging.ERROR)

    async def stop(self, ctx: Context) -> None:
        self._player.stop()
        self._queue_manager.clear()
        self._message_service.reset()
        await self._set_chill_activity()
        await self._message_service.send(ctx, "Player is stopped!")

    async def pause(self, ctx: Context) -> None:
        if self._player.is_in_any_status(PlayerStatus.PLAYING):
            self._player.pause()
            await self._message_service.send(ctx, "Paused!")
        elif self._player.is_in_any_status(PlayerStatus.NOT_PLAYING):
            await self._message_service.send(ctx, "Bot doesn't play anything!", logging.WARNING)
        elif self._player.is_in_any_status(PlayerStatus.PAUSED):
            await self._message_service.send(ctx, "Bot is already paused!", logging.WARNING)

    async def resume(self, ctx: Context) -> None:
        if self._player.is_in_any_status(PlayerStatus.PLAYING):
            await self._message_service.send(ctx, "Bot is already resumed!", logging.WARNING)
        elif self._player.is_in_any_status(PlayerStatus.NOT_PLAYING):
            await self._message_service.send(ctx, "Bot doesn't play anything!", logging.WARNING)
        elif self._player.is_in_any_status(PlayerStatus.PAUSED):
            self._player.resume()
            await self._message_service.send(ctx, "Resumed!")

    async def next(self, ctx: Context) -> None:
        if track := self._queue_manager.try_get_next():
            self._player.stop()
            await asyncio.sleep(SLEEP_TIME)
            await self._player.try_play(
                track=track,
                on_success_play_callback=self._on_success_play_callback_factory(ctx=ctx, track=track),
                on_music_end_callback=self._on_music_end_callback_factory(ctx=ctx),
            )
        else:
            await self._message_service.send(ctx, "Can't play next music: end of queue", logging.WARNING)

    async def prev(self, ctx: Context) -> None:
        if track := self._queue_manager.try_get_prev():
            self._player.stop()
            await asyncio.sleep(SLEEP_TIME)
            await self._player.try_play(
                track=track,
                on_success_play_callback=self._on_success_play_callback_factory(ctx=ctx, track=track),
                on_music_end_callback=self._on_music_end_callback_factory(ctx=ctx),
            )
        else:
            await self._message_service.send(ctx, "Can't play prev music: end of queue", logging.WARNING)

    async def jump(self, ctx: Context, index: int) -> None:
        if track := self._queue_manager.jump_to(index):
            self._player.stop()
            await asyncio.sleep(SLEEP_TIME)
            await self._player.try_play(
                track=track,
                on_success_play_callback=self._on_success_play_callback_factory(ctx=ctx, track=track),
                on_music_end_callback=self._on_music_end_callback_factory(ctx=ctx),
            )
        else:
            await self._message_service.send(ctx, "Invalid index value", logging.ERROR)

    async def remove(self, ctx: Context, index: int) -> None:
        current_track = self._queue_manager.get_current()
        removed = self._queue_manager.remove_at(index)

        if removed is None:
            await self._message_service.send(ctx, "Invalid index value", logging.ERROR)

            return

        if current_track == removed:
            self._player.stop()
            if track := self._queue_manager.get_next():
                await self._player.try_play(
                    track=track,
                    on_success_play_callback=self._on_success_play_callback_factory(ctx=ctx, track=track),
                    on_music_end_callback=self._on_music_end_callback_factory(ctx=ctx),
                )
            else:
                await self._set_chill_activity()

        await self._message_service.send(ctx, f"Track number - {index + 1} is removed!")

    async def shuffle(self, ctx: Context) -> None:
        self._queue_manager.shuffle()
        await self._message_service.send(ctx, "Queue is shuffled!")

    async def now_playing(self, ctx: Context) -> None:
        if track := self._queue_manager.get_current():
            current_time, full_time = self._player.get_played_and_full_time(track)
            time_string = "STREAM" if track.stream_link else f"{current_time} - {full_time}"
            await self._message_service.send(ctx, f"{track.title} [{time_string}]\n{track.link}")
        else:
            await self._message_service.send(ctx, "Nothing is playing")

    async def set_music_parameters(
        self,
        ctx: Context,
        bass_value: int | None = None,
        volume_value: int | None = None,
    ) -> None:
        if bass_value is not None:
            self._settings.bass_value = bass_value

        if volume_value is not None:
            self._settings.volume_value = volume_value

        track = self._queue_manager.get_current()
        if self._player.is_in_any_status(PlayerStatus.PLAYING) and track is not None:
            current_time, _ = self._player.get_played_and_full_time(track)
            current_time += timedelta(seconds=SLEEP_TIME)
            self._player.stop()
            await asyncio.sleep(SLEEP_TIME)
            track.start_time = current_time
            await self._player.try_play(
                track=track,
                on_success_play_callback=self._on_success_play_callback_factory(ctx=ctx, track=track, notify=False),
                on_music_end_callback=self._on_music_end_callback_factory(ctx=ctx),
            )

        if self._player.is_in_any_status(PlayerStatus.PAUSED):
            self._player.pause()

        self._settings.dump_config()

    async def loop(self, ctx: Context) -> None:
        is_looped = self._queue_manager.toggle_loop()
        if is_looped:
            await self._message_service.send(ctx, "Queue is looped")
        else:
            await self._message_service.send(ctx, "Queue is unlooped")

    async def show_queue(self, ctx: Context) -> None:
        self._message_service.reset()
        await self._message_service.send_show_queue(
            ctx,
            self._get_track_infos_for_show_queue(),
            self._queue_manager.get_queue_length(),
        )

    async def on_message_reaction_add(self, reaction: Reaction, user: Member | User) -> None:
        if self._message_service.is_reaction_on_show_queue_message(reaction):
            self._message_service.on_show_queue_message_reaction_add(
                reaction,
                self._queue_manager.get_queue_length(),
                self._queue_manager.get_current_index(),
            )

            await self._message_service.update_show_queue(
                reaction,
                self._get_track_infos_for_show_queue(),
                self._queue_manager.get_queue_length(),
                user,
            )

    def _get_track_infos_for_show_queue(self) -> list[TrackInfo]:
        offset, limit = self._message_service.get_show_queue_offset_and_limit()
        tracks = self._queue_manager.get_many(limit=limit + 1, offset=offset)
        current_track = self._queue_manager.get_current()
        interrupting_track = self._queue_manager.get_interrupting()

        if interrupting_track is not None:
            tracks.insert(0, interrupting_track)

        track_infos = []
        i = offset
        for track in tracks:
            played_time, full_time = self._player.get_played_and_full_time(track)
            track_info = TrackInfo(
                is_current=current_track == track,
                played_time=played_time,
                full_time=full_time,
                is_stream=bool(track.stream_link),
                is_interrupting=interrupting_track == track,
                title=track.title,
                download_done=bool(not track.download_task or track.download_task.done()),
            )

            if interrupting_track != track:
                track_info.queue_index = i
                i += 1

            track_infos.append(track_info)

        return track_infos

    async def _set_chill_activity(self) -> None:
        await self._voice_client.client.change_presence(
            status=Status.online,
            activity=Activity(
                name="Не могу стоять пока другие работают... пойду полежу",
                type=ActivityType.watching,
            ),
        )

    async def _download(
        self,
        source: str,
        ctx: Context,
        start_time: timedelta | None = None,
        *,
        is_im_track: bool = False,
        force_load_first: bool = False,
    ) -> list[Track]:
        try:
            tracks = await self._download_service.download(
                source=source,
                only_one=is_im_track,
                force_load_first=force_load_first,
            )
        except (CantDownloadError, CantLoadTrackInfoError) as e:
            await self._message_service.send(ctx, str(e), logging.ERROR)
        except (RuntimeError, OSError, ValueError, KeyError) as e:
            await self._message_service.send(ctx, "Looks like some bug happened, so, can't download music")
            logger.exception("Unexpected error occurred", exc_info=e)
        else:
            first_track = tracks[0]

            if start_time:
                first_track.start_time = start_time

            await self._message_service.send(ctx, f"Downloaded {len(tracks)} by source {source}")

            return tracks

        return []

    def _on_music_end_callback_factory(
        self,
        ctx: Context,
    ) -> Callable:
        def callback(error: Exception | None) -> None:
            if error:
                logger.error(error)
            elif self._player.is_in_any_status(PlayerStatus.PLAYING, PlayerStatus.PAUSED):
                self._player.stop()
                if track := self._queue_manager.get_next():
                    self._voice_client.loop.create_task(
                        self._player.try_play(
                            track=track,
                            on_success_play_callback=self._on_success_play_callback_factory(ctx=ctx, track=track),
                            on_music_end_callback=self._on_music_end_callback_factory(ctx=ctx),
                        )
                    )
                else:
                    self._voice_client.loop.create_task(self._set_chill_activity())

        return callback

    def _on_success_play_callback_factory(self, ctx: Context, track: Track, *, notify: bool = True) -> Callable:
        async def callback() -> None:
            if notify:
                time_str = (
                    "STREAM" if track.stream_link else f"{track.start_time} - {timedelta(seconds=track.duration)}"
                )
                await self._message_service.send(
                    ctx,
                    f"Now is playing - {track.title} [{time_str}]\nLink - {track.link}",
                )
            await self._voice_client.client.change_presence(
                status=Status.online,
                activity=Activity(name=track.title, type=ActivityType.listening),
            )

        return callback

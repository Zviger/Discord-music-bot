import asyncio
import logging
import random
import threading
import time
from datetime import timedelta, datetime
from asyncio import AbstractEventLoop
from enum import Enum
from pathlib import Path
from threading import Thread
from typing import Tuple, Optional
from urllib import parse

import psutil
from dateutil import parser
from discord import (
    PCMVolumeTransformer,
    FFmpegPCMAudio,
    VoiceClient,
    Embed,
    Colour,
    Status,
    Activity,
    ActivityType,
    Message,
    Emoji,
)
from discord.ext.commands import Context

from config import config
from exceptions import CantDownloadException, BatchDownloadNotAllowed, CantLoadTrackInfoException
from models import Track
from music_downloaders.yandex import YandexMusicDownloader
from music_downloaders.youtube import YouTubeDownloader
from music_info_loaders.spotify import SpotifyInfoLoader
from settings import settings
from utils import SearchDomains

logger = logging.getLogger(settings.app_name)

SLEEP_TIME = 0.10
THREAD_COUNT = 8


class PlayerStatus(Enum):
    PLAYING: int = 0
    NOT_PLAYING: int = 1
    PAUSED: int = 2


class MusicHandler:
    def __init__(self, voice_client, loop: AbstractEventLoop):
        self._voice_client: VoiceClient = voice_client
        self._loop: AbstractEventLoop = loop
        self._queue = []
        self._current_queue_track: Optional[Track] = None
        self._current_im_track: Optional[Track] = None
        self._status = PlayerStatus.NOT_PLAYING
        self._is_loop_queue: bool = False
        self._show_queue_message: Optional[Message] = None
        self._show_queue_first_index = 0
        self._show_queue_length = 8
        self._lock = threading.Lock()
        self._ym_downloader = YandexMusicDownloader(
            token=config.tokens["yandex_music"], cache_dir=settings.cached_music_dir
        )
        self._yt_downloader = YouTubeDownloader(cache_dir=settings.cached_music_dir)
        self._spt_info_loader = SpotifyInfoLoader(
            client_id=config.tokens["spotify_client_id"],
            client_secret=config.tokens["spotify_client_secret"],
        )
        self._stream_download_proc = None
        self._stream_file_path = None

    async def add_to_playlist(
        self,
        source: str,
        ctx: Context,
        start_time: Optional[datetime],
        write_message: bool = True,
    ):
        tracks = await self._download(
            source=source,
            ctx=ctx,
            start_time=start_time,
            write_message=write_message,
        )
        if tracks:
            self._lock.acquire()
            await self._add_tracks_to_queue(tracks)
            self._lock.release()

    async def play(
        self,
        source: str,
        ctx: Context,
        start_time: Optional[datetime],
        download_message: bool = True,
    ):
        tracks = await self._download(
            source=source,
            ctx=ctx,
            start_time=start_time,
            write_message=download_message,
            force_load_first=True,
        )
        if tracks:
            self._lock.acquire()
            await self._add_tracks_to_queue(tracks)
            self._lock.release()
            await self._try_play(ctx, tracks[0])

    async def set_not_playing_status(self) -> None:
        self._status = PlayerStatus.NOT_PLAYING
        await self._set_chill_activity()

    async def stop(self, ctx: Context):
        if self._status in (PlayerStatus.PLAYING, PlayerStatus.PAUSED):
            self._status = PlayerStatus.NOT_PLAYING
            self._voice_client.stop()
            self._queue.clear()
            self._current_queue_track = None
            self._current_im_track = None
            self._show_queue_first_index = 0
            await self._set_chill_activity()
            await self._send_message(ctx, "Stopped!")
        elif self._status == PlayerStatus.NOT_PLAYING:
            await self._send_message(ctx, "Bot doesn't play anything!", logging.WARNING)

    async def pause(self, ctx: Context):
        if self._status == PlayerStatus.PLAYING:
            self._status = PlayerStatus.PAUSED
            self._voice_client.pause()
            await self._send_message(ctx, "Paused!")
        elif self._status == PlayerStatus.NOT_PLAYING:
            await self._send_message(ctx, "Bot doesn't play anything!", logging.WARNING)
        else:
            await self._send_message(ctx, "Bot is already paused!", logging.WARNING)

    async def resume(self, ctx: Context):
        if self._status == PlayerStatus.PLAYING:
            await self._send_message(ctx, "Bot is already resumed!", logging.WARNING)
        elif self._status == PlayerStatus.NOT_PLAYING:
            await self._send_message(ctx, "Bot doesn't play anything!", logging.WARNING)
        else:
            self._status = PlayerStatus.PLAYING
            self._voice_client.resume()
            await self._send_message(ctx, "Resumed!")

    async def next(self, ctx: Context) -> None:
        if track := self._get_next_track():
            self._status = PlayerStatus.NOT_PLAYING
            self._voice_client.stop()
            time.sleep(0.25)
            await self._try_play(ctx, track)
        else:
            await self._send_message(ctx, f"Can't play next music: end of queue", logging.WARNING)
            await self._set_chill_activity()

    async def prev(self, ctx: Context) -> None:
        if track := self._get_prev_track():
            self._status = PlayerStatus.NOT_PLAYING
            self._voice_client.stop()
            time.sleep(0.25)
            await self._try_play(ctx, track)
        else:
            await self._send_message(ctx, f"Can't play prev music: end of queue", logging.WARNING)
            await self._set_chill_activity()

    async def jump(self, ctx: Context, index: int) -> None:
        try:
            self._queue[index]
        except IndexError:
            await self._send_message(ctx, "Invalid index value", logging.ERROR)
            return

        self._status = PlayerStatus.NOT_PLAYING
        self._current_im_track = None
        self._voice_client.stop()
        time.sleep(SLEEP_TIME)
        await self._try_play(ctx, self._queue[index])

    async def show_queue(self, ctx: Context):
        self._show_queue_first_index = self._get_current_track_position()
        embed = await self._get_show_queue_embed()
        message: Message
        message = self._show_queue_message = await ctx.send(embed=embed)

        if self._show_queue_first_index or len(self._queue) > self._show_queue_length:
            await message.add_reaction(settings.arrow_up_small)
            await message.add_reaction(settings.arrow_down_small)
            await message.add_reaction(settings.record_button)
            await message.add_reaction(settings.double_arrow_up_small)
            await message.add_reaction(settings.double_arrow_down_small)

    async def _get_show_queue_embed(self) -> Embed:
        current_id = self._get_current_track_position()
        embed = Embed(title=f"Queue of {len(self._queue)} tracks")

        if track := self._current_im_track:
            current_time, full_time = self._current_full_time()

            current_time = current_time.strftime("%H:%M:%S")
            full_time = full_time.strftime("%H:%M:%S")
            current_track_strings = (
                f"{track.title} " f"[{'STREAM' if track.is_stream else f'{current_time} - {full_time}'}]"
            )
            embed.add_field(name="Immediately track", value=f"```css\n{current_track_strings or 'empty'}```")

        current_index = self._show_queue_first_index
        if current_index is not None:
            for i, track in tuple(enumerate(self._queue))[current_index : current_index + self._show_queue_length]:
                if i == current_id and not self._current_im_track and self._current_queue_track:
                    current_time, full_time = self._current_full_time()
                    current_time = current_time.strftime("%H:%M:%S")
                    full_time = full_time.strftime("%H:%M:%S")
                    embed.add_field(
                        name=f"{i + 1}) Current track "
                        f"[{'STREAM' if track.is_stream else f'{current_time} - {full_time}'}]",
                        value=f"```css\n{track.title}```",
                        inline=False,
                    )
                else:
                    embed.add_field(
                        name=f"{i + 1}) {'STREAM' if track.is_stream else timedelta(seconds=track.duration)}",
                        value=f"```css\n{track.title}```",
                        inline=False,
                    )

        embed.colour = Colour.blue()

        return embed

    def is_show_query_message(self, message: Message):
        return self._show_queue_message and message.id == self._show_queue_message.id

    async def move_show_query(self, emoji: Emoji):
        queue_length = self._show_queue_length
        old_index = self._show_queue_first_index
        if emoji == settings.arrow_down_small:
            if old_index + queue_length < len(self._queue):
                self._show_queue_first_index += queue_length
                if self._show_queue_first_index > len(self._queue) - self._show_queue_length:
                    self._show_queue_first_index = len(self._queue) - self._show_queue_length
        elif emoji == settings.arrow_up_small:
            if self._show_queue_first_index - queue_length >= 0:
                self._show_queue_first_index -= queue_length
            else:
                if old_index > 0:
                    self._show_queue_first_index = 0
        elif emoji == settings.double_arrow_up_small:
            self._show_queue_first_index = 0
        elif emoji == settings.double_arrow_down_small:
            self._show_queue_first_index = len(self._queue) - self._show_queue_length
        else:
            self._show_queue_first_index = self._get_current_track_position()

        if old_index != self._show_queue_first_index:
            embed = await self._get_show_queue_embed()
            await self._show_queue_message.edit(embed=embed)

    async def remove(self, ctx: Context, index: int) -> None:
        try:
            self._queue[index]
        except IndexError:
            await self._send_message(ctx, "Invalid index value", logging.ERROR)
            return

        current_id = self._get_current_track_position()

        if index == current_id:
            self._status = PlayerStatus.NOT_PLAYING
            self._voice_client.stop()
            if track := self._get_next_track(empty_im=False):
                await self._try_play(ctx, track)
            else:
                self._current_queue_track = None
                await self._set_chill_activity()
            self._queue.pop(index)
        else:
            self._queue.pop(index)

        await self._send_message(ctx, f"Track number - {index + 1} is removed!")

    async def shuffle(self, ctx: Context):
        current_track = self._queue.pop(self._get_current_track_position())
        random.shuffle(self._queue)
        self._queue = [current_track] + self._queue
        await self._send_message(ctx, "Queue is shuffled!")

    async def now_playing(self, ctx: Context):
        if track := self._current_track:
            current_time, full_time = self._current_full_time()
            current_time = current_time.strftime("%H:%M:%S")
            full_time = full_time.strftime("%H:%M:%S")
            await self._send_message(
                ctx, f"{track.title} [{'STREAM' if track.is_stream else f'{current_time} - {full_time}'}]\n{track.link}"
            )
        else:
            await self._send_message(ctx, f"Nothing is playing")

    async def im_play(
        self,
        source: str,
        ctx: Context,
        start_time: datetime,
    ):
        tracks = await self._download(source, ctx, start_time, is_im_track=True)
        track = tracks[0]

        if track:
            if self._status == PlayerStatus.PLAYING:
                current_time, _ = self._current_full_time()
                self._status = PlayerStatus.NOT_PLAYING
                self._voice_client.stop()
                if self._current_queue_track is not None:
                    self._current_queue_track.start_time = current_time
                time.sleep(SLEEP_TIME)
                self._current_im_track = track
                await self._try_play(ctx, track, is_im_track=True)
            elif self._status == PlayerStatus.NOT_PLAYING:
                self._current_im_track = track
                await self._try_play(ctx, track, is_im_track=True)
            else:
                await self._send_message(ctx, f"Music shouldn't be paused!", logging.ERROR)

    async def set_music_parameters(
        self,
        ctx: Context,
        bass_value: Optional[int] = None,
        volume_value: Optional[int] = None,
    ):
        if bass_value is not None:
            config.bass_value = bass_value

        if volume_value is not None:
            config.volume_value = volume_value

        if self._status == PlayerStatus.PLAYING:
            current_time, _ = self._current_full_time()
            current_time = current_time + timedelta(seconds=SLEEP_TIME)
            self._status = PlayerStatus.NOT_PLAYING
            self._voice_client.stop()
            time.sleep(SLEEP_TIME)
            self._current_track.start_time = current_time
            await self._try_play(ctx, self._current_track, msg=False, is_im_track=bool(self._current_im_track))

        if self._status == PlayerStatus.PAUSED:
            self._status = PlayerStatus.PAUSED
            self._voice_client.pause()

        config.dump_config()

    async def loop(self, ctx: Context):
        if self._is_loop_queue:
            self._is_loop_queue = False
            await self._send_message(ctx, "Queue is unlooped")
        else:
            self._is_loop_queue = True
            await self._send_message(ctx, "Queue is looped")

    async def _send_message(self, ctx: Context, message: str, level: int = logging.INFO, not_only_log=True):
        embed = Embed(title=message if len(message) <= 256 else f"{message[:253]}...")
        if level == logging.INFO:
            logger.info(message)
            embed.colour = Colour.blue()
        elif level == logging.WARNING:
            logger.warning(message)
            embed.colour = Colour.from_rgb(255, 255, 0)
        elif level == logging.ERROR:
            logger.error(message)
            embed.colour = Colour.red()

        if not_only_log:
            await asyncio.create_task(ctx.send(embed=embed))

    async def _try_play(self, ctx: Context, track: Track, is_im_track: bool = False, msg: bool = True):
        if self._status not in (PlayerStatus.PLAYING, PlayerStatus.PAUSED):
            if track.download_task:
                await track.download_task

            track.im_start_time = track.start_time
            start_time = track.start_time.strftime("%H:%M:%S")
            track.start_time = parser.parse("00:00:00")

            if track.is_stream:
                Thread(target=self._yt_downloader._client.download, args=(track.link,)).start()
                time_sleep = 5
                if track.is_twitch:
                    time_sleep = 30
                time.sleep(time_sleep)

                self._stream_download_proc = [
                    proc for proc in psutil.process_iter() if proc.name().startswith("ffmpeg")
                ][-1]
                self._stream_file_path = Path(settings.cached_music_dir).joinpath(track.id)

                self._voice_client.play(
                    PCMVolumeTransformer(
                        FFmpegPCMAudio(str(self._stream_file_path), options=f"-af bass=g={config.bass_value}"),
                        volume=config.volume_value / 100,
                    ),
                    after=self._on_music_end(ctx),
                )
            else:
                self._voice_client.play(
                    PCMVolumeTransformer(
                        FFmpegPCMAudio(
                            str(Path(settings.cached_music_dir).joinpath(track.id)),
                            before_options=f"-ss {start_time}",
                            options=f"-af bass=g={config.bass_value}",
                        ),
                        volume=config.volume_value / 100,
                    ),
                    after=self._on_music_end(ctx),
                )
            self._status = PlayerStatus.PLAYING

            if is_im_track:
                self._current_im_track = track
            else:
                self._current_queue_track = track

            if msg:
                await self._send_message(
                    ctx,
                    f"Now is playing - {track.title} ["
                    f"{'STREAM' if track.is_stream else f'{start_time} - {timedelta(seconds=track.duration)}'}"
                    f"]\nLink - {track.link}",
                )
            await self._voice_client.client.change_presence(
                status=Status.online, activity=Activity(name=track.title, type=ActivityType.listening)
            )

    async def _set_chill_activity(self) -> None:
        await self._voice_client.client.change_presence(
            status=Status.online,
            activity=Activity(
                name="Не могу стоять пока другие работают... пойду полежу", type=ActivityType.watching
            ),
        )

    def _on_music_end(self, ctx: Context):
        def on_music_end(error) -> None:
            if self._stream_download_proc is not None:
                self._stream_download_proc.kill()
                self._stream_download_proc = None
                self._stream_file_path.unlink()

            if error:
                logger.error(error)
            else:
                if self._status in (PlayerStatus.PLAYING, PlayerStatus.PAUSED):
                    self._status = PlayerStatus.NOT_PLAYING
                    if track := self._get_next_track():
                        self._loop.create_task(self._try_play(ctx, track))
                    else:
                        self._loop.create_task(self._set_chill_activity())
                        self._current_queue_track = None
                        self._current_im_track = None

        return on_music_end

    def _current_full_time(self) -> Tuple[datetime, datetime]:
        track = self._current_track
        a_timedelta = track.im_start_time - parser.parse("00:00:00")
        seconds = a_timedelta.total_seconds()
        current_time = timedelta(seconds=self._voice_client._player.loops * 0.02 + seconds) + parser.parse("00:00:00")
        full_time = timedelta(seconds=track.duration) + parser.parse("00:00:00")

        return current_time, full_time

    async def _add_tracks_to_queue(self, tracks: list[Track]) -> None:
        self._queue.extend(tracks)

    async def _download(
        self,
        source: str,
        ctx: Context,
        start_time: Optional[datetime] = None,
        write_message: bool = True,
        is_im_track: bool = False,
        force_load_first: bool = False,
    ) -> list[Track]:
        parsed_url = parse.urlparse(source)
        netloc = parsed_url.netloc

        try:
            if netloc.startswith(SearchDomains.yandex_music):
                tracks = await self._ym_downloader.download(
                    source=source,
                    batch_download_allowed=not is_im_track,
                    force_load_first=force_load_first,
                )
            elif netloc.startswith(SearchDomains.spotify):
                track_names = await self._spt_info_loader.get_track_names(source=source)

                if is_im_track and len(track_names) > 1:
                    raise BatchDownloadNotAllowed

                tracks = await self._yt_downloader.batch_download_by_track_names(
                    track_names=track_names,
                    force_load_first=force_load_first,
                )
            else:
                tracks = await self._yt_downloader.download(
                    source=source,
                    batch_download_allowed=not is_im_track,
                    force_load_first=force_load_first,
                )
        except (CantDownloadException, CantLoadTrackInfoException) as e:
            if write_message:
                await self._send_message(ctx, str(e), logging.ERROR)

            return []
        except BatchDownloadNotAllowed:
            if write_message:
                await self._send_message(ctx, "Can't play more then one track immediately")

            return []
        except Exception as e:
            if write_message:
                await self._send_message(ctx, "Looks like some bug happened, so, can't download music")
            logger.exception("Some error occurred", exc_info=e)
        else:
            first_track = tracks[0]

            if start_time:
                first_track.start_time = start_time

            if write_message:
                await self._send_message(ctx, f"Downloaded {len(tracks)} by source {source}")

            return tracks

    @property
    def _current_track(self) -> Track:
        return self._current_im_track or self._current_queue_track

    def _get_current_track_position(self) -> Optional[int]:
        if not self._current_queue_track and self._queue:
            return 0

        for i in range(len(self._queue)):
            if self._queue[i].uuid == self._current_queue_track.uuid:
                return i
        return None

    def _get_next_track(self, empty_im=True) -> Optional[Track]:
        if self._current_im_track and empty_im and self._queue:
            self._current_im_track = None

            return self._current_queue_track

        if (current_queue_track_position := self._get_current_track_position()) is not None:
            next_queue_tack_position = current_queue_track_position + 1
            if next_queue_tack_position == len(self._queue) and self._is_loop_queue:
                return self._queue[0]
            elif next_queue_tack_position < len(self._queue):
                return self._queue[next_queue_tack_position]
            else:
                return None
        return None

    def _get_prev_track(self, empty_im=True) -> Optional[Track]:
        if self._current_im_track and empty_im and self._queue:
            self._current_im_track = None

            return self._current_queue_track

        if (current_queue_track_position := self._get_current_track_position()) is not None:
            prev_queue_tack_position = current_queue_track_position - 1

            if prev_queue_tack_position == -1 and self._is_loop_queue:
                return self._queue[-1]
            elif prev_queue_tack_position > -1:
                return self._queue[prev_queue_tack_position]
            else:
                return None
        return None

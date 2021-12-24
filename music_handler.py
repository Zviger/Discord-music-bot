import datetime
import itertools
import logging
import random
import threading
import time
from asyncio import AbstractEventLoop
from enum import Enum
from pathlib import Path
from threading import Thread
from time import gmtime, strftime, struct_time
from typing import Tuple, Optional, List
from urllib import parse

import yt_dlp as youtube_dl
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
    Emoji
)
from discord.ext.commands import Context
import yandex_music

from config import config
from models import Track
from settings import settings
from spotify import Spotify
from utils import chunks, SearchDomains

logger = logging.getLogger(settings.app_name)

SLEEP_TIME = 0.10
THREAD_COUNT = 8


class PlayerStatus(Enum):
    PLAYING: int = 0
    NOT_PLAYING: int = 1
    PAUSED: int = 2


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


YDL_OPTIONS = {
    "format": "bestaudio",
    "outtmpl": f"{settings.cached_music_dir}/%(id)s",
    "ignoreerrors": True,
    "skip-unavailable-fragments": True,
    "youtube-skip-dash-manifest": True,
    "cache-dir": "~/.cache/youtube-dl",
    "logger": YtLogger,
    "default_search": "ytsearch",

}


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
        self._ym_client = yandex_music.Client(token=config.tokens["yandex_music"], report_new_fields=False)
        self._ydl = youtube_dl.YoutubeDL(YDL_OPTIONS)
        self._sf_client = Spotify(config.tokens["spotify_client_id"], config.tokens["spotify_client_secret"])

    def add_to_playlist(
            self,
            source: str,
            ctx: Context,
            start_time: Optional[datetime.datetime],
            write_message: bool = True
    ):
        track = self._download(source, ctx, start_time, write_message=write_message)
        if track is not None:
            self._lock.acquire()
            self._add_track_to_queue(track)
            self._lock.release()

    def batch_add_to_playlist(
            self,
            sources: List[str],
            ctx: Context,
    ):
        for source in sources:
            self.add_to_playlist(source, ctx, None, False)

    def batch_thread_add_to_playlist(
            self,
            sources: List[str],
            ctx: Context
    ):
        for chunk in chunks(sources, len(sources) // THREAD_COUNT + 1):
            thread = Thread(target=self.batch_add_to_playlist, args=(chunk, ctx))
            thread.start()

    def play(
            self,
            source: str,
            ctx: Context,
            start_time: Optional[datetime.datetime],
            download_message: bool = True):
        track = self._download(source, ctx, start_time, download_message)
        if track is not None:
            self._lock.acquire()
            self._add_track_to_queue(track)
            self._lock.release()
            self._try_play(ctx, track)

    def set_not_playing_status(self) -> None:
        self._status = PlayerStatus.NOT_PLAYING

    def stop(self, ctx: Context):
        if self._status in (PlayerStatus.PLAYING, PlayerStatus.PAUSED):
            self._status = PlayerStatus.NOT_PLAYING
            self._voice_client.stop()
            self._queue.clear()
            self._current_queue_track = None
            self._current_im_track = None
            self._show_queue_first_index = 0
            self._send_message(ctx, "Stopped!")
        elif self._status == PlayerStatus.NOT_PLAYING:
            self._send_message(ctx, "Bot doesn't play anything!", logging.WARNING)

    def pause(self, ctx: Context):
        if self._status == PlayerStatus.PLAYING:
            self._status = PlayerStatus.PAUSED
            self._voice_client.pause()
            self._send_message(ctx, "Paused!")
        elif self._status == PlayerStatus.NOT_PLAYING:
            self._send_message(ctx, "Bot doesn't play anything!", logging.WARNING)
        else:
            self._send_message(ctx, "Bot is already paused!", logging.WARNING)

    def resume(self, ctx: Context):
        if self._status == PlayerStatus.PLAYING:
            self._send_message(ctx, "Bot is already resumed!", logging.WARNING)
        elif self._status == PlayerStatus.NOT_PLAYING:
            self._send_message(ctx, "Bot doesn't play anything!", logging.WARNING)
        else:
            self._status = PlayerStatus.PLAYING
            self._voice_client.resume()
            self._send_message(ctx, "Resumed!")

    def next(self, ctx: Context) -> None:
        if self._status in (PlayerStatus.PLAYING, PlayerStatus.PAUSED):
            if track := self._get_next_track():
                self._status = PlayerStatus.NOT_PLAYING
                self._voice_client.stop()
                time.sleep(0.25)
                self._try_play(ctx, track)
            else:
                self._send_message(ctx, f"Can't play next music: end of queue", logging.WARNING)
                self._set_chill_activity()
        elif self._status == PlayerStatus.NOT_PLAYING:
            self._send_message(ctx, "Bot doesn't play anything!", logging.WARNING)

    async def show_queue(self, ctx: Context):
        self._show_queue_first_index = self._get_current_track_position()
        embed = self._get_show_queue_embed()
        message: Message
        message = self._show_queue_message = await ctx.send(embed=embed)

        if self._show_queue_first_index or len(self._queue) > self._show_queue_length:
            await message.add_reaction(settings.arrow_up_small)
            await message.add_reaction(settings.arrow_down_small)
            await message.add_reaction(settings.record_button)
            await message.add_reaction(settings.double_arrow_up_small)
            await message.add_reaction(settings.double_arrow_down_small)

    def _get_show_queue_embed(self) -> Embed:
        current_id = self._get_current_track_position()
        embed = Embed(title=f"Queue of {len(self._queue)} tracks")

        if track := self._current_im_track:
            current_time, full_time = self._current_full_time()
            current_time = strftime("%H:%M:%S", current_time)
            full_time = strftime("%H:%M:%S", full_time)
            current_track_strings = f"{track.title} [{current_time} - {full_time}]"
            embed.add_field(name="Immediately track", value=f"```css\n{current_track_strings or 'empty'}```")

        current_index = self._show_queue_first_index
        if current_index is not None:
            for i, track in tuple(enumerate(self._queue))[current_index:current_index + self._show_queue_length]:
                if i == current_id and not self._current_im_track and self._current_queue_track:
                    current_time, full_time = self._current_full_time()
                    current_time = strftime("%H:%M:%S", current_time)
                    full_time = strftime("%H:%M:%S", full_time)
                    embed.add_field(
                        name=f"{i + 1}) Current track [{current_time} - {full_time}]",
                        value=f"```css\n{track.title}```",
                        inline=False
                    )
                else:
                    embed.add_field(
                        name=f"{i + 1}) {datetime.timedelta(seconds=track.length)}",
                        value=f"```css\n{track.title}```",
                        inline=False
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
            embed = self._get_show_queue_embed()
            await self._show_queue_message.edit(embed=embed)

    def jump(self, ctx: Context, index: int) -> None:
        try:
            self._queue[index]
        except IndexError:
            self._send_message(ctx, "Invalid index value", logging.ERROR)
            return

        self._status = PlayerStatus.NOT_PLAYING
        self._current_im_track = None
        self._voice_client.stop()
        time.sleep(SLEEP_TIME)
        self._try_play(ctx, self._queue[index])

    def remove(self, ctx: Context, index: int) -> None:
        try:
            self._queue[index]
        except IndexError:
            self._send_message(ctx, "Invalid index value", logging.ERROR)
            return

        current_id = self._get_current_track_position()

        if index == current_id:
            self._status = PlayerStatus.NOT_PLAYING
            self._voice_client.stop()
            if track := self._get_next_track(empty_im=False):
                self._try_play(ctx, track)
            else:
                self._current_queue_track = None
                self._set_chill_activity()
            self._queue.pop(index)
        else:
            self._queue.pop(index)

        self._send_message(ctx, f"Track number - {index + 1} is removed!")

    def shuffle(self, ctx: Context):
        current_track = self._queue.pop(self._get_current_track_position())
        random.shuffle(self._queue)
        self._queue = [current_track] + self._queue
        self._send_message(ctx, "Queue is shuffled!")

    def now_playing(self, ctx: Context):
        if track := self._current_track:
            current_time, full_time = self._current_full_time()
            current_time = strftime("%H:%M:%S", current_time)
            full_time = strftime("%H:%M:%S", full_time)
            self._send_message(ctx, f"{track.title} [{current_time} - {full_time}]\n{track.link}")
        else:
            self._send_message(ctx, f"Nothing is playing")

    def im_play(
            self,
            source: str,
            ctx: Context,
            start_time: datetime.datetime,
    ):
        track = self._download(source, ctx, start_time, is_im_track=True)

        if track:
            if self._status == PlayerStatus.PLAYING:
                current_time, _ = self._current_full_time()
                current_time = datetime.datetime.fromtimestamp(time.mktime(current_time))
                self._status = PlayerStatus.NOT_PLAYING
                self._voice_client.stop()
                if self._current_queue_track is not None:
                    self._current_queue_track.start_time = current_time
                time.sleep(SLEEP_TIME)
                self._current_im_track = track
                self._try_play(ctx, track, is_im_track=True)
            elif self._status == PlayerStatus.NOT_PLAYING:
                self._current_im_track = track
                self._try_play(ctx, track, is_im_track=True)
            else:
                self._send_message(ctx, f"Music shouldn't be paused!", logging.ERROR)

    def set_music_parameters(
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
            current_time = datetime.datetime.fromtimestamp(time.mktime(current_time) + SLEEP_TIME)
            self._status = PlayerStatus.NOT_PLAYING
            self._voice_client.stop()
            time.sleep(SLEEP_TIME)
            self._current_track.start_time = current_time
            self._try_play(ctx, self._current_track, msg=False)

        if self._status == PlayerStatus.PAUSED:
            self._status = PlayerStatus.PAUSED
            self._voice_client.pause()

        config.dump_config()

    def loop(self, ctx: Context):
        if self._is_loop_queue:
            self._is_loop_queue = False
            self._send_message(ctx, "Queue is unlooped")
        else:
            self._is_loop_queue = True
            self._send_message(ctx, "Queue is looped")

    def default(self, _, ctx: Context, __):
        with open("default_playlist", "r+") as file:
            track_urls = file.readlines()
            random.shuffle(track_urls)

            if len(track_urls) == 1:
                self.play(track_urls[0].strip(), ctx, None, False)

            if len(track_urls) == 2:
                self.batch_thread_add_to_playlist(track_urls[1:], ctx)

    def _send_message(self, ctx: Context, message: str, level: int = logging.INFO, not_only_log=True):
        embed = Embed(title=message)
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
            self._loop.create_task(ctx.send(embed=embed))

    def _try_play(self, ctx: Context, track: Track, is_im_track: bool = False, msg=True):
        if self._status not in (PlayerStatus.PLAYING, PlayerStatus.PAUSED):
            track.im_start_time = track.start_time
            start_time = track.start_time.strftime("%H:%M:%S")
            track.start_time = parser.parse("00:00:00")
            self._voice_client.play(
                PCMVolumeTransformer(
                    FFmpegPCMAudio(
                        Path(settings.cached_music_dir).joinpath(track.id),
                        before_options=f"-ss {start_time}",
                        options=f"-af bass=g={config.bass_value}"
                    ),
                    volume=config.volume_value / 100
                ),
                after=self._on_music_end(ctx),
            )
            self._status = PlayerStatus.PLAYING

            if is_im_track:
                self._current_im_track = track
            else:
                self._current_queue_track = track
            if msg:
                self._send_message(
                    ctx,
                    f"Now is playing - {track.title} [{start_time} -"
                    f" {datetime.timedelta(seconds=track.length)}]\nLink - {track.link}"
                )
            self._loop.create_task(
                self._voice_client.client.change_presence(
                    status=Status.online, activity=Activity(name=track.title, type=ActivityType.listening)
                )
            )

    def _set_chill_activity(self) -> None:
        self._loop.create_task(
            self._voice_client.client.change_presence(
                status=Status.online, activity=Activity(
                    name="Не могу стоять пока другие работают... пойду полежу",
                    type=ActivityType.watching
                )
            )
        )

    def _on_music_end(self, ctx: Context):
        def on_music_end(error) -> None:
            if error:
                logger.error(error)
            else:
                if self._status in (PlayerStatus.PLAYING, PlayerStatus.PAUSED):
                    self._status = PlayerStatus.NOT_PLAYING
                    if track := self._get_next_track():
                        self._try_play(ctx, track)
                    else:
                        self._set_chill_activity()

        return on_music_end

    def _current_full_time(self) -> Tuple[struct_time, struct_time]:
        track = self._current_track
        a_timedelta = track.im_start_time - parser.parse("00:00:00")
        seconds = a_timedelta.total_seconds()

        return gmtime(self._voice_client._player.loops * 0.02 + seconds), gmtime(track.length)

    def _add_track_to_queue(self, track: Track) -> None:
        self._queue.append(track)

    def _download(
            self,
            source: str,
            ctx: Context,
            start_time: Optional[datetime.datetime] = None,
            write_message: bool = True,
            is_im_track: bool = False
    ) -> Optional[Track]:
        parsed_url = parse.urlparse(source)
        netloc = parsed_url.netloc

        if (
                netloc.startswith(SearchDomains.youtube.value)
                or netloc.startswith(SearchDomains.youtube_short.value)
                or not netloc
        ):
            track_info = self._ydl.extract_info(source, download=False)

            if not netloc:
                entries = track_info["entries"]
                if entries:
                    track_info = entries[0]
                    self._ydl.download(track_info["original_url"])
                else:
                    if write_message:
                        self._send_message(ctx, f"Cant download youtube music {source}", logging.ERROR)
                    return None

            elif entries := track_info.get("entries"):
                if is_im_track:
                    self._send_message(ctx, "Can't play more then one track immediately")
                    return

                write_message = False
                start_time = None
                track_info = entries[0]
                self._ydl.download(track_info["original_url"])
                self.batch_thread_add_to_playlist([entry["original_url"] for entry in entries[1:] if entry], ctx)
            else:
                self._ydl.download(track_info["original_url"])

            track = Track(
                id=track_info["id"],
                title=track_info["title"].strip(),
                link=track_info["original_url"].strip(),
                length=track_info["duration"],
                creation_time=time.time()
            )
        elif netloc.startswith(SearchDomains.yandex_music.value):
            path_args = parsed_url.path.strip("/").split("/")

            if len(path_args) == 2 and path_args[0] == "album" and path_args[1].isnumeric():
                if is_im_track:
                    self._send_message(ctx, "Can't play more then one track immediately")
                    return

                tracks = list(itertools.chain(*self._ym_client.albums_with_tracks(int(path_args[1])).volumes))
                track = tracks[0]
                self._download_ym_track(track)
                self.batch_thread_add_to_playlist(
                    [
                        f"https://music.yandex.by/album/{(ids := t.track_id.split(':'))[1]}/track/{ids[0]}"
                        for t in tracks[1:]
                    ],
                    ctx
                )
            elif (
                    len(path_args) == 4
                    and path_args[0] == "users"
                    and path_args[2] == "playlists"
                    and path_args[3].isnumeric()
            ):
                if is_im_track:
                    self._send_message(ctx, "Can't play more then one track immediately")
                    return
                user_login, playlist_id = path_args[1], int(path_args[3])
                tracks = self._ym_client.users_playlists(playlist_id, user_login).tracks
                track = tracks[0].track
                self._download_ym_track(track)
                self.batch_thread_add_to_playlist(
                    [
                        f"https://music.yandex.by/album/{(ids := t.track.track_id.split(':'))[1]}/track/{ids[0]}"
                        for t in tracks[1:]
                    ],
                    ctx
                )
            elif (
                    len(path_args) == 4
                    and path_args[0] == "album"
                    and path_args[1].isnumeric()
                    and path_args[2] == "track"
                    and path_args[3].isnumeric()
            ):
                track = self._ym_client.tracks(f"{path_args[3]}:{path_args[1]}")[0]
                self._download_ym_track(track)
            else:
                if write_message:
                    self._send_message(ctx, f"Cant download yandex music", logging.ERROR)
                return None

            track = Track(
                id=track.track_id,
                title=track.title,
                link=source,
                length=track.duration_ms // 1000,
                creation_time=time.time()
            )
        elif netloc.startswith(SearchDomains.spotify.value):
            path_args = parsed_url.path.split("/")

            if "track" in path_args:
                response = self._sf_client.get_track(path_args[-1])
                track_name = f"{response['artists'][0]['name']} {response['name']}"

                return self._download(track_name, ctx, start_time, write_message)
            elif "album" in path_args:
                if is_im_track:
                    self._send_message(ctx, "Can't play more then one track immediately")
                    return

                response = self._sf_client.get_album(path_args[-1])
                track_names = [f"{i['name']} {i['artists'][0]['name']}" for i in response["tracks"]["items"]]
                result = self._download(track_names[0], ctx, start_time, write_message)
                self.batch_thread_add_to_playlist(track_names[1:], ctx)

                return result
            elif "playlist" in path_args:
                if is_im_track:
                    self._send_message(ctx, "Can't play more then one track immediately")
                    return

                tracks = []
                response = self._sf_client.get_playlist_tracks(path_args[-1])
                while True:
                    tracks.extend(response["items"])
                    if response["next"] is not None:
                        response = self._sf_client.make_spotify_req(response["next"])
                        continue
                    else:
                        break

                track_names = [f"{i['track']['name']} {i['track']['artists'][0]['name']}" for i in tracks]
                result = self._download(track_names[0], ctx, start_time, write_message)
                self.batch_thread_add_to_playlist(track_names[1:], ctx)

                return result
            else:
                if write_message:
                    self._send_message(ctx, f"Cant download spotify music", logging.ERROR)
                return None
        else:
            if write_message:
                self._send_message(ctx, f"Cant download music", logging.ERROR)
            return None

        if start_time:
            track.start_time = start_time

        if write_message:
            self._send_message(ctx, f"Downloaded music - {track.title}")

        return track

    @staticmethod
    def _download_ym_track(track: yandex_music.Track):
        if not (filepath := Path(settings.cached_music_dir).joinpath(track.track_id)).exists():
            track.download(str(filepath), codec="aac", bitrate_in_kbps=128)

    @property
    def _current_track(self) -> Track:
        return self._current_im_track or self._current_queue_track

    def _get_current_track_position(self) -> Optional[int]:
        if not self._current_queue_track and self._queue:
            return 0

        for i in range(len(self._queue)):
            if self._queue[i].creation_time == self._current_queue_track.creation_time:
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
                self._current_queue_track = None
                return None
        return None

import logging
import os
import shutil
from asyncio import wait_for
from pathlib import Path
from typing import Union, Optional, Tuple, Callable

from discord import (
    User,
    Member,
    VoiceState,
    TextChannel,
    File,
    VoiceChannel,
    VoiceClient,
    Message,
    Guild,
    Status,
    ActivityType,
    Activity,
    Reaction,
)
from discord.ext.commands import Bot, Context

from config import config
from music_handler import MusicHandler
from settings import settings
from utils import send_message, parse_play_args

logger = logging.getLogger(settings.app_name)


class MusicBot(Bot):
    def __init__(self, command_prefix, **options) -> None:
        super().__init__(command_prefix, **options)
        self.music_handler: Optional[MusicHandler] = None
        self.prepare_and_play = self.setup_commands()

    def get_guild_voice_client(self, ctx: Context) -> Optional[VoiceClient]:
        author = ctx.author
        for voice_client in self.voice_clients:
            if voice_client.guild == author.guild:
                return voice_client
        return None

    def is_voice_client_here(self, ctx: Context) -> bool:
        voice_client = self.get_guild_voice_client(ctx)

        return voice_client and voice_client.channel == ctx.author.voice.channel

    async def on_ready(self) -> None:
        logger.info(f"We have logged in as {self.user}")
        await self.change_presence(status=Status.online, activity=Activity(name="кочалке", type=ActivityType.competing))

    async def on_reaction_add(self, reaction: Reaction, user: Union[Member, User]) -> None:
        if (
            user.id != self.user.id
            and self.music_handler
            and self.music_handler.is_show_query_message(reaction.message)
            and reaction.emoji in (
                    settings.arrow_up_small,
                    settings.arrow_down_small,
                    settings.record_button,
                    settings.double_arrow_up_small,
                    settings.double_arrow_down_small,
            )
        ):
            await self.music_handler.move_show_query(reaction.emoji)
            message: Message = reaction.message
            await message.remove_reaction(reaction, user)

    async def on_message(self, message: Message) -> None:
        if message.author == self.user:
            return

        if message.mention_everyone:
            await message.channel.send(
                content="Все сюдаааааааааааааа!",
                tts=True,
                file=File("images/vse_suda.jpg"),
                delete_after=100
            )
        else:
            await Bot.on_message(self, message)

    async def on_voice_state_update(self, member: Union[Member, User], before: VoiceState, _: VoiceState) -> None:
        if before.channel is None:
            if user_setting := config.users_settings.get(member.id):
                if channel_id := config.channels.get("general"):
                    channel: TextChannel = self.get_channel(channel_id)
                    logger.info(f"Send grating message to {member}")
                    await channel.send(
                        content=user_setting.gratings_text,
                        file=File(Path("images").joinpath(user_setting.gratings_image_name)),
                        delete_after=10
                    )
            else:
                logger.info(f"Member {member} is here.")

    async def on_member_ban(self, _: Guild, user: User) -> None:
        if channel_id := config.channels.get("general"):
            channel: TextChannel = self.get_channel(channel_id)
            await channel.send(
                content=f"{user.name}, бан, чучело",
                tts=True,
                file=File("images/ban.jpg")
            )

    def setup_commands(self) -> Callable:
        async def prepare_and_play(args: Tuple[str], ctx: Context, play_method: callable):
            source, start_time = parse_play_args(args)
            voice_client = self.get_guild_voice_client(ctx)
            if not voice_client:
                try:
                    await wait_for(summon(ctx, False), 10)
                    if not self.music_handler:
                        return
                except TimeoutError:
                    await send_message(ctx, "Bot summon timeout error.", logging.ERROR)
                    return

            if self.music_handler:
                if ctx.author.voice.channel != self.get_guild_voice_client(ctx).channel:
                    await send_message(ctx, "You should be in a voice channel with bot!", logging.WARNING)
                    return
                play_method(self.music_handler, source, ctx, start_time)
            else:
                await send_message(ctx, "Can't play, bot is not in voice channel!", logging.WARNING)

        @self.command(aliases=("здарова", ))
        async def hello(ctx: Context) -> None:
            """Sends hello message."""
            emoji = await ctx.guild.fetch_emoji(715199900966584361)
            await send_message(ctx, f"Hello, {ctx.author}! {emoji}")

        @self.command(aliases=("сюда", ))
        async def summon(ctx: Context, move=True) -> None:
            """Summon bot in current voice channel."""
            logger.info(f"{ctx.author} started summoning")
            author: Union[User, Member] = ctx.author
            voice_state: VoiceState = author.voice

            if not voice_state:
                await send_message(ctx, "You should be in a voice channel!", logging.WARNING)
                return

            author_voice_channel: VoiceChannel = voice_state.channel

            if voice_client := self.get_guild_voice_client(ctx):
                if not voice_client.is_connected():
                    await voice_client.channel.connect()
                if move:
                    if not self.is_voice_client_here(ctx):
                        await voice_client.move_to(author_voice_channel)
            else:
                voice_client = await author_voice_channel.connect()
                self.music_handler = MusicHandler(voice_client, self.loop)
            await send_message(ctx, "Ннннну давай!")

        @self.command(aliases=("сьеби", "съеби", "уходи", "l"))
        async def leave(ctx: Context) -> None:
            """Try to drop the bot from guild voice channels."""
            logger.info(f"{ctx.author} started leaving.")
            if self.music_handler:
                self.music_handler.set_not_playing_status()
            if self.get_guild_voice_client(ctx):
                await self.get_guild_voice_client(ctx).disconnect()
            await send_message(ctx, "На созвоне)")
            self.music_handler = None

        @self.command(aliases=("p", "навали", "н"))
        async def play(ctx: Context, *args: str) -> None:
            """Add track to queue by youtube link, yandex music link or by track name and play music, if player stopped.
            At the end of command u can add start time for playing in hh:mm:ss format.
            """
            await prepare_and_play(args, ctx, MusicHandler.play)

        @self.command(aliases=("д", "добавь", "a"))
        async def add(ctx: Context, *args: str) -> None:
            """Add track to queue by youtube link, yandex music link or by track name.
            At the end of command u can add start time for playing in hh:mm:ss format.
            """
            source, start_time = parse_play_args(args)

            if self.music_handler:
                self.music_handler.play(source, ctx, start_time)
            else:
                await send_message(ctx, "Can't add to playlist: bot is not in voice channel!", logging.WARNING)

        @self.command(aliases=("стоп", "clear"))
        async def stop(ctx: Context) -> None:
            """Stop music and empty playlist."""
            if self.is_voice_client_here(ctx):
                self.music_handler.stop(ctx)
            else:
                await send_message(ctx, "Can't stop playing: bot is not in voice channel with you!", logging.WARNING)

        @self.command(aliases=("пауза", "секундочку"))
        async def pause(ctx: Context) -> None:
            """Pause music."""
            if self.is_voice_client_here(ctx):
                self.music_handler.pause(ctx)
            else:
                await send_message(ctx, "Can't pause playing: bot is not in voice channel with you!", logging.WARNING)

        @self.command(aliases=("продолжить", "продолжим"))
        async def resume(ctx: Context) -> None:
            """Resume music."""
            if self.is_voice_client_here(ctx):
                self.music_handler.resume(ctx)
            else:
                await send_message(ctx, "Can't resume playing: bot is not in voice channel with you!", logging.WARNING)

        @self.command(aliases=("n", "скип", "с"), name="next")
        async def skip(ctx: Context) -> None:
            """Skip music."""
            if self.is_voice_client_here(ctx):
                self.music_handler.next(ctx)
            else:
                await send_message(ctx, "Can't play next music: bot is not in voice channel with you!", logging.WARNING)

        @self.command(aliases=("q", "очередь"), name="queue")
        async def show_queue(ctx: Context) -> None:
            """Resume music."""
            if self.music_handler:
                await self.music_handler.show_queue(ctx)
            else:
                await send_message(ctx, "Can't show queue: bot is not in voice channel!", logging.WARNING)

        @self.command(aliases=("j", "никита"))
        async def jump(ctx: Context, *args: str):
            """Jump on specific track in queue by index."""
            if self.is_voice_client_here(ctx):
                try:
                    index = int(args[0])
                    if index > 0:
                        index -= 1
                except ValueError:
                    await send_message(ctx, "Invalid index!", logging.ERROR)
                    return

                self.music_handler.jump(ctx, index)
            else:
                await send_message(ctx, "Can't jump: bot is not in voice channel with you!", logging.WARNING)

        @self.command(aliases=("r", "удалить"))
        async def remove(ctx: Context, *args: str) -> None:
            """Remove on specific track in queue by index."""
            if self.is_voice_client_here(ctx):
                try:
                    index = int(args[0])
                    if index > 0:
                        index -= 1
                except ValueError:
                    await send_message(ctx, "Invalid index!", logging.ERROR)
                    return

                self.music_handler.remove(ctx, index)
            else:
                await send_message(ctx, "Can't remove: bot is not in voice channel with you!", logging.WARNING)

        @self.command(aliases=("замешать",))
        async def shuffle(ctx: Context) -> None:
            """Shuffle queue."""
            if self.is_voice_client_here(ctx):
                self.music_handler.shuffle(ctx)
            else:
                await send_message(ctx, "Can't shuffle: bot is not in voice channel with you!", logging.WARNING)

        @self.command(aliases=("чичас", "np"))
        async def now_playing(ctx: Context) -> None:
            """Show current track."""
            if self.music_handler is not None:
                self.music_handler.now_playing(ctx)
            else:
                await send_message(ctx, "Can't show it: bot is not in voice channel with!", logging.WARNING)

        @self.command(aliases=("im", "прямща"))
        async def im_play(ctx: Context, *args: str) -> None:
            """Pause playlist, play this music and resume playlist."""
            await prepare_and_play(args, ctx, MusicHandler.im_play)

        @self.command(aliases=("бас",))
        async def bass(ctx: Context, *args) -> None:
            """Set bass value."""
            if args:
                if self.is_voice_client_here(ctx):
                    if not args[0].isnumeric():
                        await send_message(ctx, f"Invalid value!", logging.ERROR)
                        return

                    value = int(args[0])
                    self.music_handler.set_music_parameters(ctx, bass_value=value)
                    await send_message(ctx, f"Bass is setted - {value}")
                else:
                    await send_message(ctx, "Can't set bass: bot is not in voice channel with you!", logging.WARNING)
            else:
                await send_message(ctx, f"Bass value - {config.bass_value}")

        @self.command(aliases=("звук",))
        async def volume(ctx: Context, *args: str) -> None:
            """Set volume value."""
            if args:
                if self.is_voice_client_here(ctx):
                    if not args[0].isnumeric():
                        await send_message(ctx, f"Invalid value!", logging.ERROR)
                        return

                    value = int(args[0])
                    self.music_handler.set_music_parameters(ctx, volume_value=value)
                    await send_message(ctx, f"Volume is setted - {value}")
                else:
                    await send_message(ctx, "Can't set volume: bot is not in voice channel with you!", logging.WARNING)
            else:
                await send_message(ctx, f"Volume value - {config.volume_value}")

        @self.command(aliases=("залупи",))
        async def loop(ctx: Context) -> None:
            """Loop/unloop the queue."""
            if self.is_voice_client_here(ctx):
                self.music_handler.loop(ctx)
            else:
                await send_message(
                    ctx,
                    "Can't loop/unloop queue: bot is not in voice channel with you!", logging.WARNING
                )

        @self.command(aliases=("дефолт", ))
        async def default(ctx: Context):
            """Loads tracks from default list."""
            await self.prepare_and_play(tuple(), ctx, MusicHandler.default)

        @self.command(aliases=("нога",))
        async def restart(ctx: Context) -> None:
            """Restart the bot."""
            settings.restart = True

            try:
                await leave(ctx)
            except Exception as e:
                logger.error(str(e))

            await self.close()

        @self.command()
        async def sys_info(ctx: Context) -> None:
            """Shows system information."""
            st = os.statvfs(".")
            free_space = int(st.f_bavail * st.f_frsize / 1024 / 1024)
            free_memory = int(os.popen("free -t -m").readlines()[-1].split()[3])

            await send_message(ctx, f"Free space - {free_space}mb\nFree memory - {free_memory}mb")

        @self.command()
        async def free_cache(ctx: Context) -> None:
            """removes cached tracks."""
            shutil.rmtree(settings.cached_music_dir)
            await send_message(ctx, "Cached tracks are removed")

        return prepare_and_play

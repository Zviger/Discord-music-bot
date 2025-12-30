import logging
from asyncio import wait_for
from datetime import timedelta
from typing import TYPE_CHECKING

from dateutil import parser
from discord import Member, Reaction, User, VoiceClient
from discord.ext import commands

from bot.factory import ServiceFactory
from config.settings import Settings
from core.logging import logger

if TYPE_CHECKING:
    from services.music import MusicService


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot, settings: Settings, service_factory: ServiceFactory) -> None:
        self._bot = bot
        self._settings = settings
        self._service_factory = service_factory
        self._message_service = service_factory.create_message_service()
        self._music_service: MusicService | None = None

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: Reaction, user: Member | User) -> None:
        if self._bot.user is not None and user.id != self._bot.user.id and self._music_service is not None:
            await self._music_service.on_message_reaction_add(reaction, user)

    @commands.command(aliases=("нога",))
    async def restart(self, ctx: commands.Context) -> None:
        """Restart the bot."""
        self._settings.restart = True

        try:
            await self.leave(ctx)
        except Exception:  # noqa: BLE001
            logger.exception("Restart error")

        await self._bot.close()

    @commands.command(aliases=("сюда",))
    async def summon(self, ctx: commands.Context, *, move: bool = True) -> None:
        """Summon bot in current voice channel."""
        logger.info("%s started summoning", ctx.author)
        author = ctx.author

        if not isinstance(author, Member) or author.voice is None or author.voice.channel is None:
            await self._message_service.send(ctx, "You should be in a voice channel!", logging.WARNING)

            return

        author_voice_channel = author.voice.channel

        if voice_client := self._get_guild_voice_client(ctx):
            if not voice_client.is_connected():
                await voice_client.disconnect(force=True)
                await voice_client.channel.connect(timeout=60, reconnect=True, self_deaf=True)

            if move and not self._is_voice_client_here(ctx):
                await voice_client.move_to(author_voice_channel)
        else:
            voice_client = await author_voice_channel.connect()
            self._music_service = self._service_factory.create_music_service(voice_client=voice_client)

        await self._message_service.send(ctx, "Ннннну давай!")

    @commands.command(aliases=("сьеби", "съеби", "уходи", "l"))
    async def leave(self, ctx: commands.Context) -> None:
        """Try to drop the bot from guild voice channels."""
        logger.info("%s started leaving.", str(ctx.author))

        if self._music_service:
            await self._music_service.stop(ctx)

        if (voice_client := self._get_guild_voice_client(ctx)) is not None:
            await voice_client.disconnect()

        await self._message_service.send(ctx, "На созвоне)")
        self._music_service = None

    @commands.command(aliases=("p", "навали", "н"))
    async def play(self, ctx: commands.Context, *args: str) -> None:
        """Add track to queue by youtube link, yandex music link or by track name and play music, if player stopped.
        At the end of command u can add start time for playing in hh:mm:ss format.
        """
        source, start_time = self._parse_play_args(args)
        await self._prepare_defore_play(ctx)

        if self._music_service is not None:
            await self._music_service.play(source=source, ctx=ctx, start_time=start_time)

    @commands.command(aliases=("im", "прямща"))
    async def im_play(self, ctx: commands.Context, *args: str) -> None:
        """Pause playlist, play this music and resume playlist."""
        source, start_time = self._parse_play_args(args)
        await self._prepare_defore_play(ctx)

        if self._music_service is not None:
            await self._music_service.im_play(source=source, ctx=ctx, start_time=start_time)

    @commands.command(aliases=("д", "добавь", "a"))
    async def add(self, ctx: commands.Context, *args: str) -> None:
        """Add track to queue by youtube link, yandex music link or by track name.
        At the end of command u can add start time for playing in hh:mm:ss format.
        """
        source, start_time = self._parse_play_args(args)

        if self._music_service:
            await self._music_service.add_to_playlist(source, ctx, start_time)
        else:
            await self._message_service.send(
                ctx, "Can't add to playlist: bot is not in voice channel!", logging.WARNING
            )

    @commands.command(aliases=("стоп", "clear"))
    async def stop(self, ctx: commands.Context) -> None:
        """Stop music and empty playlist."""
        if self._is_voice_client_here(ctx) and self._music_service is not None:
            await self._music_service.stop(ctx)
        else:
            await self._message_service.send(
                ctx,
                "Can't stop playing: bot is not in voice channel with you or doesn't play anything!",
                logging.WARNING,
            )

    @commands.command(aliases=("пауза", "секундочку"))
    async def pause(self, ctx: commands.Context) -> None:
        """Pause music."""
        if self._is_voice_client_here(ctx) and self._music_service is not None:
            await self._music_service.pause(ctx)
        else:
            await self._message_service.send(
                ctx, "Can't pause playing: bot is not in voice channel with you!", logging.WARNING
            )

    @commands.command(aliases=("продолжить", "продолжим", "unpause"))
    async def resume(self, ctx: commands.Context) -> None:
        """Resume music."""
        if self._is_voice_client_here(ctx) and self._music_service is not None:
            await self._music_service.resume(ctx)
        else:
            await self._message_service.send(
                ctx, "Can't resume playing: bot is not in voice channel with you!", logging.WARNING
            )

    @commands.command(aliases=("n", "скип", "с"), name="next")
    async def skip(self, ctx: commands.Context) -> None:
        """Skip music."""
        if self._is_voice_client_here(ctx) and self._music_service is not None:
            await self._music_service.next(ctx)
        else:
            await self._message_service.send(
                ctx, "Can't play next music: bot is not in voice channel with you!", logging.WARNING
            )

    @commands.command()
    async def prev(self, ctx: commands.Context) -> None:
        """Move to the previous music."""
        if self._is_voice_client_here(ctx) and self._music_service is not None:
            await self._music_service.prev(ctx)
        else:
            await self._message_service.send(
                ctx,
                "Can't play previous music: bot is not in voice channel with you!",
                logging.WARNING,
            )

    @commands.command()
    async def last(self, ctx: commands.Context) -> None:
        """Jump on the last track."""
        if self._is_voice_client_here(ctx) and self._music_service is not None:
            await self._music_service.jump(ctx, -1)
        else:
            await self._message_service.send(
                ctx,
                "Can't play the last music: bot is not in voice channel with you!",
                logging.WARNING,
            )

    @commands.command()
    async def first(self, ctx: commands.Context) -> None:
        """Jump on the first track."""
        if self._is_voice_client_here(ctx) and self._music_service is not None:
            await self._music_service.jump(ctx, 0)

        else:
            await self._message_service.send(
                ctx,
                "Can't play the first music: bot is not in voice channel with you!",
                logging.WARNING,
            )

    @commands.command(aliases=("q", "очередь"), name="queue")
    async def show_queue(self, ctx: commands.Context) -> None:
        """Resume music."""
        if self._music_service:
            await self._music_service.show_queue(ctx)
        else:
            await self._message_service.send(ctx, "Can't show queue: bot is not in voice channel!", logging.WARNING)

    @commands.command(aliases=("j", "никита"))
    async def jump(self, ctx: commands.Context, *args: str) -> None:
        """Jump on specific track in queue by index."""
        if not args:
            await self._message_service.send(ctx, "Please provide an index!", logging.ERROR)
            return

        try:
            index = int(args[0])
            if index > 0:
                index -= 1
        except (ValueError, IndexError):
            await self._message_service.send(ctx, "Invalid index!", logging.ERROR)
            return

        if not self._is_voice_client_here(ctx) or self._music_service is None:
            await self._message_service.send(ctx, "Can't jump: bot is not in voice channel with you!", logging.WARNING)
            return

        await self._music_service.jump(ctx, index)

    @commands.command(aliases=("r", "удалить"))
    async def remove(self, ctx: commands.Context, *args: str) -> None:
        """Remove on specific track in queue by index."""
        if not args:
            await self._message_service.send(ctx, "Please provide an index!", logging.ERROR)
            return

        try:
            index = int(args[0])
            if index > 0:
                index -= 1
        except (ValueError, IndexError):
            await self._message_service.send(ctx, "Invalid index!", logging.ERROR)
            return

        if not self._is_voice_client_here(ctx) or self._music_service is None:
            await self._message_service.send(
                ctx, "Can't remove: bot is not in voice channel with you!", logging.WARNING
            )
            return

        await self._music_service.remove(ctx, index)  # type: ignore[union-attr]

    @commands.command(aliases=("замешать",))
    async def shuffle(self, ctx: commands.Context) -> None:
        """Shuffle queue."""
        if self._is_voice_client_here(ctx) and self._music_service is not None:
            await self._music_service.shuffle(ctx)
        else:
            await self._message_service.send(
                ctx, "Can't shuffle: bot is not in voice channel with you!", logging.WARNING
            )

    @commands.command(aliases=("чичас", "np"))
    async def now_playing(self, ctx: commands.Context) -> None:
        """Show current track."""
        if self._music_service is not None:
            await self._music_service.now_playing(ctx)
        else:
            await self._message_service.send(ctx, "Can't show it: bot is not in voice channel with!", logging.WARNING)

    @commands.command(aliases=("бас",))
    async def bass(self, ctx: commands.Context, *args: str) -> None:
        """Set bass value."""
        if args:
            if self._is_voice_client_here(ctx) and self._music_service is not None:
                if not args[0].isnumeric():
                    await self._message_service.send(ctx, "Invalid value!", logging.ERROR)
                    return

                value = int(args[0])
                await self._music_service.set_music_parameters(ctx, bass_value=value)
                await self._message_service.send(ctx, f"Bass is setted - {value}")
            else:
                await self._message_service.send(
                    ctx, "Can't set bass: bot is not in voice channel with you!", logging.WARNING
                )
        else:
            await self._message_service.send(ctx, f"Bass value - {self._settings.bass_value}")

    @commands.command(aliases=("звук",))
    async def volume(self, ctx: commands.Context, *args: str) -> None:
        """Set volume value."""
        if args:
            if self._is_voice_client_here(ctx) and self._music_service is not None:
                if not args[0].isnumeric():
                    await self._message_service.send(ctx, "Invalid value!", logging.ERROR)
                    return

                value = int(args[0])
                await self._music_service.set_music_parameters(ctx, volume_value=value)
                await self._message_service.send(ctx, f"Volume is setted - {value}")
            else:
                await self._message_service.send(
                    ctx, "Can't set volume: bot is not in voice channel with you!", logging.WARNING
                )
        else:
            await self._message_service.send(ctx, f"Volume value - {self._settings.volume_value}")

    @commands.command(aliases=("залупи",))
    async def loop(self, ctx: commands.Context) -> None:
        """Loop/unloop the queue."""
        if self._is_voice_client_here(ctx) and self._music_service is not None:
            await self._music_service.loop(ctx)
        else:
            await self._message_service.send(
                ctx,
                "Can't loop/unloop queue: bot is not in voice channel with you!",
                logging.WARNING,
            )

    async def _prepare_defore_play(self, ctx: commands.Context) -> None:
        voice_client = self._get_guild_voice_client(ctx)

        if not voice_client or not voice_client.is_connected():
            try:
                await wait_for(self.summon(ctx, move=False), 10)
            except Exception:  # noqa: BLE001
                await self._message_service.send(ctx, "Bot summon timeout error.", logging.ERROR)
                return

        voice_client = self._get_guild_voice_client(ctx)

        if self._music_service is not None and voice_client is not None:
            if (
                not isinstance(ctx.author, Member)
                or not ctx.author.voice
                or ctx.author.voice.channel != voice_client.channel
            ):
                await self._message_service.send(ctx, "You should be in a voice channel with bot!", logging.WARNING)

                return
        else:
            await self._message_service.send(ctx, "Can't play, bot is not in voice channel!", logging.WARNING)

    def _get_guild_voice_client(self, ctx: commands.Context) -> VoiceClient | None:
        author = ctx.author

        if not isinstance(author, Member):
            return None

        for voice_client in self._bot.voice_clients:
            if author.guild in voice_client.client.guilds and isinstance(voice_client, VoiceClient):
                return voice_client

        return None

    def _is_voice_client_here(self, ctx: commands.Context) -> bool:
        voice_client = self._get_guild_voice_client(ctx)

        return (
            voice_client is not None
            and isinstance(ctx.author, Member)
            and ctx.author.voice is not None
            and voice_client.channel == ctx.author.voice.channel
        )

    def _parse_play_args(self, args: tuple[str, ...]) -> tuple[str, timedelta]:
        start_time = timedelta()
        strings = list(args)
        if len(args) > 1:
            try:
                parsed_time = parser.parse(strings[-1])
                start_time = timedelta(seconds=parsed_time.second, hours=parsed_time.hour, minutes=parsed_time.minute)
                strings.pop()
            except ValueError:
                pass

        source = " ".join(strings)
        return source, start_time

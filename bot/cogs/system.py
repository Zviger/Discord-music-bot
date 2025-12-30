from datetime import datetime
from pathlib import Path

import psutil
from discord import Activity, ActivityType, File, Guild, Member, Message, Status, TextChannel, User, VoiceState
from discord.ext import commands

from bot.factory import ServiceFactory
from config.settings import Settings
from core.logging import logger


class SystemCog(commands.Cog):
    def __init__(self, bot: commands.Bot, settings: Settings, service_factory: ServiceFactory) -> None:
        self._bot = bot
        self._settings = settings
        self._message_service = service_factory.create_message_service()
        now = datetime.now()  # noqa: DTZ005
        local_now = now.astimezone()
        self._local_tz = local_now.tzinfo

    @commands.command()
    async def free_cache(self, ctx: commands.Context) -> None:
        """removes cached tracks."""
        for filename in Path(self._settings.cached_music_dir).iterdir():
            filename.unlink()

        await self._message_service.send(ctx, "Cached tracks are removed")

    @commands.command()
    async def sys_info(self, ctx: commands.Context) -> None:
        """Shows system information."""
        free_space = int(psutil.disk_usage("/").free / 1024 / 1024)
        free_memory = int(psutil.virtual_memory().free / 1024 / 1024)

        await self._message_service.send(ctx, f"Free space - {free_space}mb\nFree memory - {free_memory}mb")

    @commands.command(aliases=("здарова",))
    async def hello(self, ctx: commands.Context) -> None:
        """Sends hello message."""
        if ctx.guild is not None:
            emoji = await ctx.guild.fetch_emoji(715199900966584361)
            await self._message_service.send(ctx, f"Hello, {ctx.author}! {emoji}")

    @commands.Cog.listener()
    async def on_member_ban(self, _: Guild, user: User) -> None:
        if channel_id := self._settings.channels.get("general"):
            channel = self._bot.get_channel(channel_id)

            if isinstance(channel, TextChannel):
                await channel.send(content=f"{user.name}, бан, чучело", tts=True, file=File("images/ban.jpg"))

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: Member | User, before: VoiceState, _: VoiceState) -> None:
        if before.channel is None and isinstance(member, Member):
            member_join_at = (
                datetime.now(tz=self._local_tz)
                if member.joined_at is None
                else member.joined_at.astimezone(tz=self._local_tz)
            )
            member_join_at_delta = datetime.now(tz=self._local_tz) - member_join_at

            if (
                member_join_at_delta.seconds / 60 < 10
                and member_join_at_delta.days == 0
                and (channel_id := self._settings.channels.get("general"))
            ):
                channel = self._bot.get_channel(channel_id)

                if isinstance(channel, TextChannel):
                    await channel.send(
                        content=f"Привет, <@{member.id}>. <@{self._bot.user.id if self._bot.user else ''}> - "
                        f"это музыкальный бот, сделай его тише или замуть.",
                        mention_author=True,
                        delete_after=60,
                    )

            if user_setting := self._settings.users_settings.get(member.id):
                if channel_id := self._settings.channels.get("general"):
                    channel = self._bot.get_channel(channel_id)
                    logger.info("Send grating message to %s", str(member))

                    if isinstance(channel, TextChannel):
                        await channel.send(
                            content=user_setting.gratings_text,
                            file=File(Path("images").joinpath(user_setting.gratings_image_name)),
                            delete_after=10,
                        )
            else:
                logger.info("Member %s is here.", str(member))

    @commands.Cog.listener()
    async def on_message(self, message: Message) -> None:
        if message.author == self._bot.user:
            return

        if message.mention_everyone:
            await message.channel.send(
                content="Все сюдаааааааааааааа!",
                tts=True,
                file=File(Path("images").joinpath(self._settings.images["vse_suda"])),
                delete_after=1006,
            )

        for text, auto_reply in self._settings.auto_replies.items():
            if text.lower().strip() in message.content.lower().strip():
                await message.channel.send(
                    content=auto_reply.text,
                    file=File(Path("images").joinpath(auto_reply.image_name)),
                )
                break

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        logger.info("We have logged in as %s", str(self._bot.user))

        await self._bot.change_presence(
            status=Status.online,
            activity=Activity(name="кочалке", type=ActivityType.competing),
        )

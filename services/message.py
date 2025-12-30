import logging
from enum import StrEnum

from discord import Colour, Embed, Member, Message, Reaction, User
from discord.ext.commands import Context

from core.logging import logger
from core.models import TrackInfo


class EmojiStrings(StrEnum):
    arrow_up_small = "⬆️"
    arrow_down_small = "🔽"
    double_arrow_up_small = "⏫"
    double_arrow_down_small = "⏬"
    record_button = "⏺️"


class MessageService:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._show_queue_message: Message | None = None
        self._show_queue_first_index = 0
        self._show_queue_length = 8

    async def send(self, ctx: Context, message: str, level: int = logging.INFO) -> None:
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

        await ctx.send(embed=embed)

    async def send_show_queue(self, ctx: Context, tracks: list[TrackInfo], queue_length: int) -> None:
        embed = await self._get_show_queue_embed(tracks, queue_length)
        message = self._show_queue_message = await ctx.send(embed=embed)

        if self._show_queue_first_index > 0 or len(tracks) > self._show_queue_length:
            await message.add_reaction(EmojiStrings.arrow_up_small)
            await message.add_reaction(EmojiStrings.arrow_down_small)
            await message.add_reaction(EmojiStrings.record_button)
            await message.add_reaction(EmojiStrings.double_arrow_up_small)
            await message.add_reaction(EmojiStrings.double_arrow_down_small)

    def get_show_queue_offset_and_limit(self) -> tuple[int, int]:
        return self._show_queue_first_index, self._show_queue_length

    def is_reaction_on_show_queue_message(self, reaction: Reaction) -> bool:
        if not (self._show_queue_message and reaction.message.id == self._show_queue_message.id):
            return False

        return str(reaction.emoji) in (
            EmojiStrings.arrow_up_small,
            EmojiStrings.arrow_down_small,
            EmojiStrings.record_button,
            EmojiStrings.double_arrow_up_small,
            EmojiStrings.double_arrow_down_small,
        )

    def on_show_queue_message_reaction_add(
        self,
        reaction: Reaction,
        queue_length: int,
        current_index: int,
    ) -> None:
        emoji = str(reaction.emoji)

        if emoji == EmojiStrings.arrow_down_small:
            self._show_queue_first_index += self._show_queue_length
            self._show_queue_first_index = min(self._show_queue_first_index, queue_length - self._show_queue_length)
        elif emoji == EmojiStrings.arrow_up_small:
            self._show_queue_first_index -= self._show_queue_length
            self._show_queue_first_index = max(self._show_queue_first_index, 0)
        elif emoji == EmojiStrings.double_arrow_up_small:
            self._show_queue_first_index = 0
        elif emoji == EmojiStrings.double_arrow_down_small:
            self._show_queue_first_index = queue_length - self._show_queue_length
        else:
            self._show_queue_first_index = current_index

    async def update_show_queue(
        self,
        reaction: Reaction,
        tracks: list[TrackInfo],
        queue_length: int,
        user: Member | User,
    ) -> None:
        if self._show_queue_message is not None:
            embed = await self._get_show_queue_embed(tracks, queue_length)
            await self._show_queue_message.edit(embed=embed)

        message: Message = reaction.message
        await message.remove_reaction(reaction, user)

    async def _get_show_queue_embed(self, tracks: list[TrackInfo], queue_length: int) -> Embed:
        embed = Embed(title=f"Queue of {queue_length} tracks")

        for track in tracks:
            if track.is_interrupting:
                time_string = "STREAM" if track.is_stream else f"{track.played_time} - {track.full_time}"
                track_info = f"Immediatly playing {time_string}"
            elif track.is_current:
                time_string = "STREAM" if track.is_stream else f"{track.played_time} - {track.full_time}"
                track_info = f"{track.queue_index + 1}) Current track [{time_string}]"
            else:
                time_string = "STREAM" if track.is_stream else str(track.full_time)
                track_info = f"{track.queue_index + 1}) {time_string}"

            if not track.download_done:
                track_info += " [NOT DOWNLOADED]"

            embed.add_field(
                name=track_info,
                value=f"```css\n{track.title}```",
                inline=False,
            )

        embed.colour = Colour.blue()

        return embed

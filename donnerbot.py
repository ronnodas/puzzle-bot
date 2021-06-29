from collections.abc import Callable, Iterator
from typing import Any, Dict, Tuple, Union

import discord
from discord_slash import SlashContext

import bot


class DonnerBot(bot.PuzzleBot):
    description = "A bot to help the Donner Party hunt."

    def get_events(self) -> Iterator[callable]:
        yield from super().get_events()
        yield from (self.on_member_join, self.on_member_remove)

    def get_commands(self) -> Iterator[Tuple[Callable, Dict[str, Any]]]:
        yield from super().get_commands()
        yield self.update_party_size, {"name": "recount", "aliases": ["r"]}

    async def solve(self, ctx: SlashContext) -> None:
        await super().solve(ctx)
        count = await self.update_party_size_passively(ctx)
        puzzle_title = self.get_puzzle_title_from_context(ctx)
        await self.get_party_channel(ctx).send(
            f"Solved puzzle {puzzle_title}. We're now Donner, Party of {count}..."
        )

    @classmethod
    async def on_member_remove(cls, member: discord.Member) -> None:
        party_channel = cls.get_party_channel(member)
        n = await cls.update_party_size_passively(member)
        name = member.nick if member.nick is not None else member.name
        message = await party_channel.send(
            f"{name} has left️! We're now Donner, Party of {n}!"
        )
        await message.add_reaction("☹")

    @classmethod
    async def update_party_size(cls, ctx: SlashContext) -> None:
        """Updates party size

        Updates the party size count should it get out of sync for whatever reason. Actually renames the topmost
        channel whose name starts with 'party-of-'.

        Usage: @DonnerBot r[ecount]"""
        await cls.update_party_size_passively(ctx)
        await ctx.message.add_reaction("👍")

    @classmethod
    async def on_member_join(cls, member: discord.Member) -> None:
        party_channel = cls.get_party_channel(member)
        n = await cls.update_party_size_passively(member)
        name = member.nick if member.nick is not None else member.name
        message = await party_channel.send(
            f"{name} has joined! We're now Donner, Party of {n}!"
        )
        await message.add_reaction("😃")

    @classmethod
    async def update_party_size_passively(
        cls, ctx: Union[discord.Member, SlashContext]
    ) -> int:
        party_channel = cls.get_party_channel(ctx)
        n = cls.get_party_count(ctx)
        if n >= 0:
            num = str(n)
        else:
            num = "minus" + str(n)
        await party_channel.edit(name=("party-of-" + num))
        return n

    @classmethod
    def get_party_count(cls, ctx: SlashContext) -> int:
        solved_category = cls.get_category_by_name(ctx, "Solved")
        solved_number = len(solved_category.channels)
        for i in range(2, 10):
            solved_category = cls.get_category_by_name(ctx, f"Solved {i}")
            if solved_category is None:
                break
            solved_number += len(solved_category.channels)
        return len(ctx.guild.members) - solved_number

    @classmethod
    def get_party_channel(
        cls, ctx: Union[discord.Member, SlashContext]
    ) -> discord.TextChannel:
        for channel in ctx.guild.text_channels:
            if channel.name.startswith("party-of"):
                return channel

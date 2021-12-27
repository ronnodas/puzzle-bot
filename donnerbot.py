from contextlib import suppress
from typing import Any, Callable, Dict, Iterator, Tuple

from bot import PuzzleBot, THUMBS_UP


class DonnerBot(PuzzleBot):
    description = "A bot to help the Donner Party hunt."
    puzzles_category_name = "🧩Unsorted Puzzles"

    @property
    def events(self) -> Iterator[callable]:
        yield from super().events
        yield from (self.on_member_join, self.on_member_remove)

    @property
    def slash_commands(self) -> Iterator[Tuple[Callable, Dict[str, Any]]]:
        yield from super().slash_commands
        yield self.recount, {
            "description": "Update party size if it gets out of sync for some reason"
        }

    async def solve(self, ctx: discord_slash.SlashContext) -> None:
        response = await super().solve(ctx)
        puzzle_title = self.get_puzzle_title(ctx.channel)
        if response is not None and puzzle_title is not None:
            await self.update_party_channel(ctx.guild, f"Solved puzzle {puzzle_title}.")

    @classmethod
    async def on_member_join(cls, member: discord.Member) -> None:
        await cls.update_party_channel(member.guild, f"{member.mention} has joined 😃")

    @classmethod
    async def on_member_remove(cls, member: discord.Member) -> None:
        await cls.update_party_channel(member.guild, f"{member.mention} has left️ ☹")

    @classmethod
    async def recount(cls, ctx: discord_slash.SlashContext) -> None:
        response = await ctx.send("Updating party size", hidden=True)
        await cls.update_party_size_silently(ctx.guild)
        with suppress(AttributeError):
            await response.add_reaction(THUMBS_UP)

    @classmethod
    async def update_party_channel(cls, guild: discord.Guild, reason: str):
        count = await cls.update_party_size_silently(guild)
        await cls.get_party_channel(guild).send(
            f"{reason}\nWe're now Donner, Party of {count}..."
        )

    @classmethod
    async def update_party_size_silently(cls, guild: discord.Guild) -> int:
        party_channel = cls.get_party_channel(guild)
        n = cls.get_party_count(guild)
        await party_channel.edit(name=f"party-of-{'minus' if n < 0 else ''}{n}")
        return n

    @classmethod
    def get_party_count(cls, guild: discord.Guild) -> int:
        solved_category = cls.get_known_category(guild, cls.solved_category_name)
        solved_number = 0
        i = 2
        while solved_category is not None:
            solved_number += len(solved_category.text_channels)
            solved_category = cls.get_category(guild, f"{cls.solved_category_name} {i}")
            i += 1
        print(f"{len(guild.members)} members and {solved_number} solved puzzles")
        return len(guild.members) - solved_number

    @classmethod
    def get_party_channel(cls, guild: discord.Guild) -> discord.TextChannel:
        for channel in guild.text_channels:
            if channel.name.startswith("party-of"):
                return channel


if __name__ == "__main__":
    DonnerBot.run_from_config()

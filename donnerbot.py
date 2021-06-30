from typing import Any, Dict, Tuple, Callable, Iterator

import discord
import discord_slash

import bot


class DonnerBot(bot.PuzzleBot):
    description = "A bot to help the Donner Party hunt."

    def get_events(self) -> Iterator[callable]:
        yield from super().get_events()
        yield from (self.on_member_join, self.on_member_remove)

    def get_commands(self) -> Iterator[Tuple[Callable, Dict[str, Any]]]:
        yield from super().get_commands()
        yield self.recount, {
            "description": "Update party size if it gets out of sync for some reason"
        }

    async def solve(self, ctx: discord_slash.SlashContext) -> None:
        await super().solve(ctx)
        puzzle_title = self.get_puzzle_title(ctx.channel)
        await self.update_party_channel(ctx.guild, f"Solved puzzle {puzzle_title}.")

    @classmethod
    async def on_member_join(cls, member: discord.Member) -> None:
        await cls.update_party_channel(
            member.guild, f"{member.display_name} has joined 😃"
        )

    @classmethod
    async def on_member_remove(cls, member: discord.Member) -> None:
        await cls.update_party_channel(
            member.guild, f"{member.display_name} has left️ ☹"
        )

    @classmethod
    async def recount(cls, ctx: discord_slash.SlashContext) -> None:
        response = await ctx.send("Updating party size", hidden=True)
        await cls.update_party_size_silently(ctx.guild)
        await response.add_reaction(bot.THUMBS_UP)

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
        solved_category = cls.get_category_by_name(guild, cls.solved_category_name)
        solved_number = 0
        i = 2
        while solved_category is not None:
            solved_number += len(solved_category.channels)
            solved_category = cls.get_category_by_name(
                guild, f"{cls.solved_category_name} {i}"
            )
            i += 1
        return len(guild.members) - solved_number

    @classmethod
    def get_party_channel(cls, guild: discord.Guild) -> discord.TextChannel:
        for channel in guild.text_channels:
            if channel.name.startswith("party-of"):
                return channel


if __name__ == "__main__":
    DonnerBot.run_from_dotenv()

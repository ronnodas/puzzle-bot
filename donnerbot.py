from collections.abc import Coroutine
from typing import Any, Callable, Iterator, Optional

import disnake
from disnake.interactions import ApplicationCommandInteraction as Interaction

from bot import PuzzleBot, THUMBS_UP, add_reaction, get_category


class DonnerBot(PuzzleBot):
    description = "A bot to help the Donner Party hunt."
    puzzles_category_name = "🧩Unsorted Puzzles"

    @property
    def events(self) -> Iterator[Callable[[Any], Coroutine]]:
        yield from super().events
        yield from (self.on_member_join, self.on_member_remove)

    def register_commands(self) -> None:
        super().register_commands()
        self.client.slash_command(
            name="recount",
            description="Update party size if it gets out of sync for some reason",
        )(self.recount)

    async def solve(self, interaction: Interaction) -> None:
        response = await super().solve(interaction)
        puzzle_title = self.get_puzzle_title(interaction.channel)
        if response is not None and puzzle_title is not None:
            await self.update_party_channel(
                interaction.guild, f"Solved puzzle {puzzle_title}."
            )

    @classmethod
    async def on_member_join(cls, member: disnake.Member) -> None:
        await cls.update_party_channel(member.guild, f"{member.mention} has joined 😃")

    @classmethod
    async def on_member_remove(cls, member: disnake.Member) -> None:
        await cls.update_party_channel(member.guild, f"{member.mention} has left️ ☹")

    @classmethod
    async def recount(cls, interaction: Interaction) -> None:
        await interaction.send("Updating party size", ephemeral=True)
        await cls.update_party_size_silently(interaction.guild)
        await add_reaction(interaction, THUMBS_UP)

    @classmethod
    async def update_party_channel(cls, guild: Optional[disnake.Guild], reason: str):
        if guild is None:
            print("Could not find party channel!")
            return
        count = await cls.update_party_size_silently(guild)
        await cls.get_party_channel(guild).send(
            f"{reason}\nWe're now Donner, Party of {count}..."
        )

    @classmethod
    async def update_party_size_silently(cls, guild: Optional[disnake.Guild]) -> int:
        if guild is None:
            return 0
        party_channel = cls.get_party_channel(guild)
        n = cls.get_party_count(guild)
        await party_channel.edit(name=f"party-of-{'minus' if n < 0 else ''}{n}")
        return n

    @classmethod
    def get_party_count(cls, guild: disnake.Guild) -> int:
        solved_category = await get_category(guild, cls.solved_category_name)
        solved_number = 0
        i = 2
        while solved_category is not None:
            solved_number += len(solved_category.text_channels)
            solved_category = await get_category(
                guild, f"{cls.solved_category_name} {i}"
            )
            i += 1
        print(f"{len(guild.members)} members and {solved_number} solved puzzles")
        return len(guild.members) - solved_number

    @classmethod
    def get_party_channel(cls, guild: disnake.Guild) -> disnake.TextChannel:
        for channel in guild.text_channels:
            if channel.name.startswith("party-of"):
                return channel


if __name__ == "__main__":
    DonnerBot.run_from_config()

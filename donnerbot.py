import itertools
from collections.abc import Coroutine
from typing import Any, Callable, Iterator, Optional

import disnake
from disnake.interactions import ApplicationCommandInteraction as Interaction

from bot import PuzzleBot, THUMBS_UP, add_reaction, find_or_make_category


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
        self.client.slash_command(
            name="voice_cleanup", description="remove voice channels not in use"
        )(self.voice_cleanup)

    async def solve(self, interaction: Interaction) -> None:
        puzzle_title = await super().solve(interaction)
        if puzzle_title is not None:
            await self.update_party_channel(
                interaction.guild, f"Solved puzzle {puzzle_title}."
            )

    async def voice_cleanup(self, interaction: Interaction) -> None:
        await interaction.send("Removing all voice channels not in use", ephemeral=True)

        count = 0
        guild = interaction.guild
        if guild is None:
            return
        for channel in guild.voice_channels:
            name = channel.name.strip().lower()
            if not any(name.startswith(prefix) for prefix in ["lobby", "general"]):
                count += await self.remove_voice_channel(channel, None)
        await interaction.edit_original_message(f"Removed {count} channels")

    async def on_member_join(self, member: disnake.Member) -> None:
        await self.update_party_size_silently(member.guild)

    async def on_member_remove(self, member: disnake.Member) -> None:
        await self.update_party_size_silently(member.guild)

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
        n = await cls.get_party_count(guild)
        await party_channel.edit(name=f"party-of-{'minus' if n < 0 else ''}{n}")
        return n

    @classmethod
    async def get_party_count(cls, guild: disnake.Guild) -> int:
        solved_category = await find_or_make_category(guild, cls.solved_category_name)
        solved_number = 0
        for i in itertools.count(2):
            solved_number += len(solved_category.text_channels)
            solved_category = disnake.utils.get(
                guild.categories, name=f"{cls.solved_category_name} {i}"
            )
            if solved_category is None:
                break
        print(f"{guild.member_count} members and {solved_number} solved puzzles")
        return guild.member_count - solved_number

    @classmethod
    def get_party_channel(cls, guild: disnake.Guild) -> disnake.TextChannel:
        for channel in guild.text_channels:
            if channel.name.startswith("party-of"):
                return channel

    async def on_ready(self) -> None:
        await super().on_ready()
        await self.update_party_size_silently(self.client.get_guild(self.guild_id))


if __name__ == "__main__":
    DonnerBot.run_from_config()

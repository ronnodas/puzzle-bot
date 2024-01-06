#! /usr/bin/env python3
# coding: utf-8

from configparser import ConfigParser
import itertools
from collections.abc import Coroutine
from typing import Any, Callable, Iterator, Optional

import disnake
from disnake.interactions import ApplicationCommandInteraction as Interaction

from bot import THUMBS_UP, PuzzleBot, add_reaction, find_or_make_category


class DonnerBot(PuzzleBot):
    description = "A bot to help the Donner Party hunt."
    puzzles_category_name = "🧩Unsorted Puzzles"

    def __init__(self, other_configs: ConfigParser, **kwargs) -> None:
        super().__init__(other_configs=other_configs, **kwargs)
        self.start_party_size = int(other_configs["discord"]["party size"])

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
        puzzle_title = await super().solve(interaction)

        if puzzle_title is not None:
            await self.update_party_channel(
                interaction.guild, f"Solved puzzle {puzzle_title}."
            )

    async def on_member_join(self, member: disnake.Member) -> None:
        await self.update_party_size_silently(member.guild)

    async def on_member_remove(self, member: disnake.Member) -> None:
        await self.update_party_size_silently(member.guild)

    async def recount(self, interaction: Interaction) -> None:
        await interaction.send("Updating party size", ephemeral=True)
        await self.update_party_size_silently(interaction.guild)
        await add_reaction(interaction, THUMBS_UP)

    async def update_party_channel(self, guild: Optional[disnake.Guild], reason: str):
        if guild is None:
            print("Could not find party channel!")
            return
        count = await self.update_party_size_silently(guild)
        if (party_channel := self.get_party_channel(guild)) is not None:
            await party_channel.send(f"{reason}\nWe're now Donner, Party of {count}...")

    async def update_party_size_silently(self, guild: Optional[disnake.Guild]) -> int:
        if guild is None:
            return 0
        n = await self.get_party_count(guild)
        if (party_channel := self.get_party_channel(guild)) is not None:
            await party_channel.edit(name=f"party-of-{'minus-' if n < 0 else ''}{n}")
        return n

    async def get_party_count(self, guild: disnake.Guild) -> int:
        solved_category = await find_or_make_category(guild, self.solved_category_name)
        solved_number = 0
        for i in itertools.count(2):
            solved_number += len(solved_category.text_channels)
            solved_category = disnake.utils.get(
                guild.categories, name=f"{self.solved_category_name} {i}"
            )
            if solved_category is None:
                break
        print(f"{guild.member_count} members and {solved_number} solved puzzles")
        return self.start_party_size - solved_number

    @classmethod
    def get_party_channel(cls, guild: disnake.Guild) -> disnake.TextChannel | None:
        for channel in guild.text_channels:
            if channel.name.startswith("party-of"):
                return channel

    async def on_ready(self) -> None:
        await super().on_ready()
        await self.update_party_size_silently(self.client.get_guild(self.guild_id))


if __name__ == "__main__":
    DonnerBot.run_from_config()

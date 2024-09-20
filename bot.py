#!/usr/bin/env python3
# coding: utf-8

from collections.abc import Callable, Coroutine, Iterator
from configparser import ConfigParser
from typing import Optional, Union, cast


import disnake
import pydrive2.auth  # type: ignore
import pydrive2.drive  # type: ignore
from disnake.ext import commands
from disnake.interactions import ApplicationCommandInteraction as Interaction

Channel = Union[disnake.TextChannel, disnake.Thread, disnake.VoiceChannel]


class PuzzleDrive(pydrive2.drive.GoogleDrive):
    saved_credentials_file = "drive_credentials.json"

    def __init__(self, root_folder: str) -> None:
        self.authentication = self.get_authentication()
        if self.authentication.credentials is None:
            self.authenticate_in_command_line()
        super().__init__(self.authentication)
        print("Loaded Google Drive credentials")
        self.root_folder_id = self.get_root_folder_id(root_folder)
        self.solved_folder_id = self.get_solved_folder_id()

    def get_root_folder_id(self, root_folder_title: str) -> str:
        self.refresh_token_if_expired()
        # could be hardcoded to speed up startup
        try:
            return self.ListFile(
                {
                    "q": f"mimeType = 'application/vnd.google-apps.folder' and title = "
                    f"'{root_folder_title}'"
                }
            ).GetList()[0]["id"]
        except IndexError:
            print(
                f"Could not find {root_folder_title} in Google Drive. "
                f"Make sure to correctly set the folder name in config.ini"
            )
            exit(1)

    def get_solved_folder_id(self) -> str:
        try:
            return self.ListFile(
                {
                    "q": f"mimeType = 'application/vnd.google-apps.folder' and "
                    f"title = 'Solved' and '{self.root_folder_id}' in parents"
                }
            ).GetList()[0]["id"]
        except IndexError:
            return self.create_file("Solved", "application/vnd.google-apps.folder")[
                "id"
            ]

    def add_spreadsheet(self, title: str) -> str:
        self.refresh_token_if_expired()
        if search_list := self.ListFile(
            {
                "q": f"mimeType = 'application/vnd.google-apps.spreadsheet' and "
                f"title = '{title}' and '{self.root_folder_id}' in parents and "
                f"trashed = false"
            }
        ).GetList():
            return search_list[0]["alternateLink"]
        return self.create_file(title, "application/vnd.google-apps.spreadsheet")[
            "alternateLink"
        ]

    def create_file(self, title, mime_type):
        file = self.CreateFile(
            {
                "title": title,
                "parents": [{"id": self.root_folder_id}],
                "mimeType": mime_type,
            }
        )
        file.Upload()
        file.FetchMetadata()
        return file

    def remove_spreadsheet(self, title: str) -> None:
        self.refresh_token_if_expired()
        for folder in [self.root_folder_id, self.solved_folder_id]:
            for spreadsheet in self.ListFile(
                {
                    "q": f"mimeType = 'application/vnd.google-apps.spreadsheet' and "
                    f"title = '{title}' and '{folder}' in parents and trashed = false"
                }
            ).GetList():
                spreadsheet.Trash()

    def move_spreadsheet_to_solved(self, title: str) -> None:
        self.refresh_token_if_expired()
        for spreadsheet in self.ListFile(
            {
                "q": f"mimeType = 'application/vnd.google-apps.spreadsheet' and "
                f"title = '{title}' and '{self.root_folder_id}' in parents and "
                f"trashed = false"
            }
        ).GetList():
            spreadsheet["parents"] = [
                {"kind": "drive#fileLink", "id": self.solved_folder_id}
            ]
            spreadsheet.Upload()

    def refresh_token_if_expired(self) -> None:
        if not self.authentication.access_token_expired:
            return
        try:
            self.authentication.Refresh()
            self.authentication.SaveCredentialsFile(self.saved_credentials_file)
        except pydrive2.auth.RefreshError:
            self.authenticate_in_command_line()

    def authenticate_in_command_line(self) -> None:
        self.authentication.CommandLineAuth()
        self.authentication.SaveCredentialsFile(self.saved_credentials_file)
        print(f"Google authentication saved to {self.saved_credentials_file}")

    @classmethod
    def get_authentication(cls) -> pydrive2.auth.GoogleAuth:
        authentication = pydrive2.auth.GoogleAuth(
            settings={
                "client_config_file": "client_secrets.json",
                "get_refresh_token": True,
            }
        )
        authentication.LoadCredentialsFile(cls.saved_credentials_file)
        return authentication


THUMBS_UP = "👍"
THUMBS_DOWN = "👎"


async def find_or_make_category(
    guild: disnake.Guild, name: str
) -> disnake.CategoryChannel:
    category = disnake.utils.get(guild.categories, name=name)
    return await guild.create_category(name) if category is None else category


def title_converter(_, title: str) -> str:
    return title.replace("'", "").replace('"', "").replace("#", "").strip()


def category_has_prefix(
    category: Optional[disnake.CategoryChannel], prefix: str
) -> bool:
    return category is not None and category.name.lower().startswith(prefix.lower())


def normalize_round_name(name):
    return "".join(c.lower() for c in name if c.isalnum())


title_param = commands.Param(
    name="title",
    description="Title of the puzzle including whatever characters",
    converter=title_converter,
)

round_param = commands.Param(
    name="round",
    description="Unambiguous prefix of the round to add the puzzle to",
)


async def add_reaction(interaction: Interaction, emoji: str) -> None:
    message = await interaction.original_message()
    await message.add_reaction(emoji)


def get_admin_mention_or_empty(guild: disnake.Guild) -> str:
    admin_role = disnake.utils.get(guild.roles, name="@admin")
    return admin_role.mention if admin_role is not None else ""


class PuzzleBot:
    description = "A bot to help puzzle hunts"
    solved_category_name = "✅Solved"
    general_category_name = "💭General"  # should probably be a configuration option
    default_puzzle_category = "🧩Puzzles"

    def __init__(
        self,
        token: str,
        guild_id: int,
        drive_root_folder: str,
        rounds: bool = False,
        **_,
    ) -> None:
        self.drive = PuzzleDrive(drive_root_folder)

        self.token = token
        self.guild_id = guild_id
        self.use_rounds = rounds
        self.known_rounds = {}
        self.current_round = None if self.use_rounds else self.default_puzzle_category
        self.voices_to_oppress = set()
        self.client = commands.InteractionBot(test_guilds=[guild_id])

        for event in self.events:
            self.client.event(event)
        self.register_commands()

    def start(self) -> None:
        self.client.run(self.token)

    @property
    def events(self) -> Iterator[Callable[..., Coroutine]]:
        yield self.on_ready
        yield self.on_voice_state_update

    def register_commands(self) -> None:
        self.client.slash_command(name="puzzle", description="Add a puzzle")(
            self.add_puzzle
        )
        if self.use_rounds:
            self.client.slash_command(
                name="puzzle-in-round", description="Add a puzzle to a round"
            )(self.add_in_round)
            self.client.slash_command(name="round", description="Add a round")(
                self.round
            )
        self.client.slash_command(
            description="Toggle voice channel, use in the puzzle's text channel"
        )(self.voice)
        self.client.slash_command(
            description="Solve puzzle, use in the puzzle's text channel"
        )(self.solve)
        self.client.slash_command(
            name="remove",
            description="Remove a puzzle",
            default_member_permissions=disnake.Permissions(administrator=True),
        )(self.remove_puzzle)
        self.client.slash_command(
            name="voice_cleanup", description="remove voice channels not in use"
        )(self.manual_voice_cleanup)
        # self.client.slash_command(
        #     name="cleanup",
        #     description="ONLY USE IF YOU KNOW WHAT YOU ARE DOING: removes all puzzle channels",
        #     default_member_permissions=disnake.Permissions(administrator=True),
        # )(self.channel_cleanup)

    async def voice_cleanup(self, guild: Optional[disnake.Guild] = None) -> int:
        if guild is None:
            guild = self.client.get_guild(self.guild_id)
        if guild is None:
            return 0
        count = 0
        for channel in guild.voice_channels:
            name = channel.name.strip().lower()
            if not any(name.startswith(prefix) for prefix in ["lobby", "general"]):
                count += await self.remove_voice_channel(channel, None)
        return count

    async def before_voice_cleanup(self):
        await self.client.wait_until_ready()

    # @property
    # async def channels(self) -> Iterator[interactions.Channel]:
    #     return [
    #         interactions.Channel(**data)
    #         for data in self.http.get_all_channels(self.guild_id)
    #     ]

    # async def channel_cleanup(self, interaction: Interaction) -> None:
    #     await interaction.response.defer()
    #     guild = self.client.get_guild(self.guild_id)
    #     if guild is None:
    #         return
    #     category = await find_or_make_category(guild, "archive 2023")
    #     channels = [
    #         channel
    #         for channel in guild.text_channels
    #         if self.get_puzzle_title(channel) is not None
    #         and (channel_category := channel.category) is not None
    #         and not channel_category.name.startswith("archive")
    #     ]
    #     # print(f"Removing {len(channels)} channels:")
    #     # for channel in channels:
    #     #     print(f"    {channel.name}")
    #     # response = input("Confirm: (y/n)")
    #     # if response.lower() != "y":
    #     #     return
    #     for channel in channels:
    #         await channel.edit(category=category)
    #     await self.manual_voice_cleanup(interaction)
    #     await add_reaction(interaction, THUMBS_UP)

    async def on_ready(self) -> None:
        guild = self.client.get_guild(self.guild_id)
        if guild is not None:
            await self.create_categories(guild)
            self.known_rounds = self.parse_rounds(guild)
            self.voices_to_oppress = await self.find_voices_to_oppress(guild)
        else:
            print(f"Could not access guild {self.guild_id}")
        print(f"Logged in as {self.client.user.name} (id #{self.client.user.id})")

    async def add_puzzle(
        self,
        interaction: Interaction,
        puzzle_title: str = title_param,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            raise ValueError("Cannot access guild")
        if self.current_round is None:
            await interaction.send("No round is currently active, use /puzzle-in-round")
            await add_reaction(interaction, THUMBS_DOWN)
            return
        await self.add_puzzle_channel_to_round(
            interaction, puzzle_title, self.current_round, guild
        )

    async def add_in_round(
        self,
        interaction: Interaction,
        puzzle_title: str = title_param,
        round_name: str = round_param,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            raise ValueError("Cannot access guild")
        rounds = self.match_round(round_name)
        if isinstance(rounds, list):
            if not rounds:
                error = f"Can't find a round matching {round_name}, if you meant to create a new round use /round"
            else:
                error = f"Found more than one round matching {round_name}: {'; '.join(rounds)}"
            await interaction.send(error)
            await add_reaction(interaction, THUMBS_DOWN)
            return
        round_name = rounds
        return await self.add_puzzle_channel_to_round(
            interaction, puzzle_title, round_name, guild
        )

    async def round(
        self, interaction: Interaction, round_name: str = round_param
    ) -> None:
        guild = interaction.guild
        if guild is None:
            raise ValueError("Cannot access guild")
        await interaction.send(f"Creating round {round_name}")
        await guild.create_category(name=round_name)
        self.known_rounds[normalize_round_name(round_name)] = round_name
        if self.use_rounds:
            await self.set_round(round_name)
        await add_reaction(interaction, THUMBS_UP)

    async def solve(self, interaction: Interaction) -> Optional[str]:
        text_channel = cast(Channel, interaction.channel)
        # TODO should not need this cast since checking if TextChannel
        puzzle_title = self.get_puzzle_title(text_channel, unsolved=True)
        if not isinstance(text_channel, disnake.TextChannel) or puzzle_title is None:
            if category_has_prefix(text_channel.category, self.solved_category_name):
                await interaction.send("Puzzle already solved 🧠", ephemeral=True)
            else:
                await interaction.send(
                    "This channel is not associated to a puzzle 🤔", ephemeral=True
                )
            return
        guild = interaction.guild
        if guild is None:
            raise ValueError("Cannot access guild")
        await interaction.send(f"Marking {puzzle_title} as ✅solved")
        solved_category = await find_or_make_category(guild, self.solved_category_name)
        if len(solved_category.channels) == 50:
            await interaction.send(
                f"{get_admin_mention_or_empty(guild)} The solved category is full! 🈵"
            )
            return await add_reaction(interaction, THUMBS_DOWN)
        await text_channel.edit(category=solved_category)
        self.drive.move_spreadsheet_to_solved(puzzle_title)
        if not await self.find_and_remove_voice_channel(interaction, puzzle_title):
            self.voices_to_oppress.add(puzzle_title)
        await add_reaction(interaction, THUMBS_UP)
        return puzzle_title

    async def remove_puzzle(
        self, interaction: Interaction, puzzle_title: str = title_param
    ) -> None:
        guild = interaction.guild
        if guild is None:
            raise ValueError("Cannot access guild")
        await interaction.send(f'Removing "{puzzle_title}"')
        await self.find_and_remove_voice_channel(interaction, puzzle_title)
        text_channel = disnake.utils.get(guild.text_channels, topic=puzzle_title)
        if text_channel is not None:
            await text_channel.delete()
        self.drive.remove_spreadsheet(puzzle_title)
        await add_reaction(interaction, THUMBS_UP)

    async def voice(self, interaction: Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            raise ValueError("Cannot access guild")
        text_channel = cast(Channel, interaction.channel)
        # TODO should not need this cast since checking if TextChannel
        puzzle_title = self.get_puzzle_title(text_channel)
        if puzzle_title is None:
            await interaction.send(
                "A 🔊voice channel can only be toggled in a puzzle's text channel 🤔",
                ephemeral=True,
            )
            return
        await interaction.send(
            f"Toggling 🔊voice channel for {puzzle_title}", ephemeral=True
        )
        voice_channel = disnake.utils.get(guild.voice_channels, name=puzzle_title)
        if voice_channel is not None:
            reaction = (
                THUMBS_UP
                if await self.remove_voice_channel(voice_channel, interaction)
                else THUMBS_DOWN
            )
        else:
            await guild.create_voice_channel(
                name=puzzle_title, category=text_channel.category
            )
            reaction = THUMBS_UP
        await add_reaction(interaction, reaction)

    async def manual_voice_cleanup(self, interaction: Interaction) -> None:
        await interaction.send("Removing all voice channels not in use", ephemeral=True)
        guild = interaction.guild
        count = await self.voice_cleanup(guild)
        if count != 0:
            await interaction.edit_original_message(f"Removed {count} channel(s)")

    async def on_voice_state_update(
        self,
        member: disnake.Member,
        before: disnake.VoiceState,
        after: disnake.VoiceState,
    ) -> None:
        channel = before.channel
        if channel is None or after.channel == channel:
            return
        if not channel.members and (name := channel.name) in self.voices_to_oppress:
            await channel.delete()
            self.voices_to_oppress.remove(name)

    async def find_voices_to_oppress(self, guild: disnake.Guild) -> set[str]:
        return {
            puzzle_title
            for category in guild.categories
            if category.name.startswith(self.solved_category_name)
            for channel in category.text_channels
            if (puzzle_title := self.get_puzzle_title(channel)) is not None
            if not await self.find_and_remove_voice_channel(guild, puzzle_title)
        }

    async def create_categories(self, guild: disnake.Guild) -> None:
        to_create = (
            [self.solved_category_name]
            if self.use_rounds
            else [self.solved_category_name, self.default_puzzle_category]
        )
        for category in to_create:
            if disnake.utils.get(guild.categories, name=category) is None:
                await guild.create_category(category)

    def get_puzzle_title(
        self, channel: Channel, unsolved: bool = False
    ) -> Optional[str]:
        if not isinstance(channel, disnake.TextChannel) or channel.topic is None:
            return None
        category = channel.category
        if unsolved and category_has_prefix(category, self.solved_category_name):
            return None
        return channel.topic.strip()

    def parse_rounds(self, guild: disnake.Guild) -> dict[str, str]:
        rounds = {}
        for category in guild.categories:
            if category_has_prefix(category, self.solved_category_name):
                continue
            if category_has_prefix(category, "archive"):
                continue
            category = category.name
            if category == self.general_category_name:
                continue
            normalized = normalize_round_name(category)
            rounds[normalized] = category
        return rounds

    def match_round(self, round_name: str) -> str | list[str]:
        round_name = normalize_round_name(round_name)
        matches = [
            name
            for normalized, name in self.known_rounds.items()
            if normalized.startswith(round_name)
        ]
        return matches[0] if len(matches) == 1 else matches

    async def set_round(self, round_name: str) -> None:
        self.current_round = round_name
        activity = disnake.Activity(name=round_name)
        await self.client.change_presence(activity=activity)

    async def add_puzzle_channel_to_round(
        self,
        interaction: Interaction,
        puzzle_title: str,
        round_name: str,
        guild: disnake.Guild,
    ) -> None:
        category = disnake.utils.get(guild.categories, name=round_name)
        if category is None:
            await interaction.send(
                f"Something went wrong; maybe the category {round_name} was deleted or created manually?"
            )
            await add_reaction(interaction, THUMBS_DOWN)
            self.known_rounds = self.parse_rounds(guild)
            return
        if self.use_rounds:
            await interaction.send(
                f"Creating puzzle {puzzle_title} in round {round_name}"
            )
        else:
            await interaction.send(f"Creating puzzle {puzzle_title}")
        existing_channel = disnake.utils.get(guild.text_channels, topic=puzzle_title)
        if existing_channel is not None:
            await interaction.send(
                f"There's already a puzzle called {puzzle_title} at {existing_channel.mention}"
            )
            await add_reaction(interaction, THUMBS_DOWN)
        link = self.drive.add_spreadsheet(puzzle_title)
        channel = await self.add_puzzle_text_channel(
            guild, puzzle_title, category=category
        )
        link_message = await channel.send(
            f"I found a 📔spreadsheet for this puzzle at {link}"
        )
        await link_message.pin()
        await guild.create_voice_channel(name=puzzle_title, category=category)
        if self.use_rounds:
            await self.set_round(round_name)
        await interaction.edit_original_message(
            content=f'Created 🧩 "{puzzle_title}" at {channel.mention}'
        )

    @classmethod
    def run_from_config(cls) -> None:
        config = ConfigParser()
        config.read("config.ini")
        bot = cls(
            token=config["discord"]["token"],
            drive_root_folder=config["Google drive"]["root folder"],
            guild_id=int(config["discord"]["guild id"]),
            rounds=config["general"].getboolean("rounds", fallback=False),
            other_configs=config,
        )
        bot.start()

    @classmethod
    async def add_puzzle_text_channel(
        cls, guild: disnake.Guild, puzzle_title: str, category: disnake.CategoryChannel
    ) -> disnake.TextChannel:
        return await guild.create_text_channel(
            name=puzzle_title, topic=puzzle_title, category=category
        )

    @classmethod
    async def find_and_remove_voice_channel(
        cls, context: Interaction | disnake.Guild, name: str
    ) -> bool:
        interaction = context if isinstance(context, Interaction) else None
        guild = context.guild if isinstance(context, Interaction) else context
        if guild is None:
            raise ValueError("Could not access message guild")
        channel = disnake.utils.get(guild.voice_channels, name=name)
        if channel is not None:
            return await cls.remove_voice_channel(channel, interaction)
        return True

    @classmethod
    async def remove_voice_channel(
        cls, voice_channel: disnake.VoiceChannel, interaction: Optional[Interaction]
    ) -> bool:
        if voice_channel.members:
            if interaction is not None:
                await interaction.send("Not removing voice channel in use 🗣️")
            return False
        else:
            await voice_channel.delete()
            return True


if __name__ == "__main__":
    PuzzleBot.run_from_config()

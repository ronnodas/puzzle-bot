#!/usr/bin/env python3
# coding: utf-8
from configparser import ConfigParser
from contextlib import suppress
from typing import Any, Callable, Dict, Iterable, Iterator, Optional, Tuple

import discord
import discord.ext.commands
import discord_slash
import pydrive.auth
import pydrive.drive


class PuzzleDrive(pydrive.drive.GoogleDrive):
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
            solved_folder = self.CreateFile(
                {
                    "title": "Solved",
                    "parents": [{"id": self.root_folder_id}],
                    "mimeType": "application/vnd.google-apps.folder",
                }
            )
            solved_folder.Upload()
            solved_folder.FetchMetadata()
            return solved_folder["id"]

    def add_spreadsheet(self, title: str) -> str:
        self.refresh_token_if_expired()
        search_list = self.ListFile(
            {
                "q": f"mimeType = 'application/vnd.google-apps.spreadsheet' and "
                f"title = '{title}' and '{self.root_folder_id}' in parents and "
                f"trashed = false"
            }
        ).GetList()
        if search_list:
            return search_list[0]["alternateLink"]
        spreadsheet = self.CreateFile(
            {
                "title": title,
                "parents": [{"id": self.root_folder_id}],
                "mimeType": "application/vnd.google-apps.spreadsheet",
            }
        )
        spreadsheet.Upload()
        spreadsheet.FetchMetadata()
        return spreadsheet["alternateLink"]

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
        except pydrive.auth.RefreshError:
            self.authenticate_in_command_line()

    def authenticate_in_command_line(self) -> None:
        self.authentication.CommandLineAuth()
        self.authentication.SaveCredentialsFile(self.saved_credentials_file)
        print(f"Google authentication saved to {self.saved_credentials_file}")

    @classmethod
    def get_authentication(cls) -> pydrive.auth.GoogleAuth:
        authentication = pydrive.auth.GoogleAuth()
        authentication.LoadCredentialsFile(cls.saved_credentials_file)
        return authentication


THUMBS_UP = "👍"
THUMBS_DOWN = "👎"


class PuzzleBot(discord.ext.commands.Bot):
    description = "A bot to help puzzle hunts"
    puzzles_category_name = "🧩Puzzles"
    solved_category_name = "✅Solved"
    voice_category_name = "🧩Puzzle Voice Channels"
    required_permissions = discord.Permissions(
        add_reactions=True,
        embed_links=True,
        manage_channels=True,
        manage_messages=True,
        read_messages=True,
        send_messages=True,
        view_channel=True,
        use_slash_commands=True,
    )

    def __init__(
        self, drive_root_folder: str, guild_id: int, **options: Dict[str, Any]
    ) -> None:
        super().__init__(
            discord.ext.commands.when_mentioned,
            description=self.description,
            **options,
        )
        self.guild_id = guild_id
        self.drive = PuzzleDrive(drive_root_folder)
        self.slash_command_handler = discord_slash.SlashCommand(self)

    async def register_commands_and_events(self) -> None:
        for event in self.events:
            self.event(event)
        for command, kwargs in self.slash_commands:
            self.slash_command_handler.slash(guild_ids=[self.guild_id], **kwargs)(
                command
            )
        await self.slash_command_handler.sync_all_commands()

    async def on_ready(self) -> None:
        print(
            f"Logged in as {self.user.name} (id #{self.user.id}) on {self.active_guild}"
        )
        permissions = self.active_guild.me.guild_permissions
        if not self.required_permissions <= permissions:
            await self.print_oauth_url()
            exit(1)
        await self.register_commands_and_events()
        await self.create_categories(
            self.active_guild,
            (
                self.puzzles_category_name,
                self.solved_category_name,
                self.voice_category_name,
            ),
        )
        print("------")

    @property
    def active_guild(self) -> discord.Guild:
        return self.get_guild(self.guild_id)

    @property
    def events(self) -> Iterator[Callable]:
        yield self.on_ready

    @property
    def slash_commands(self) -> Iterator[Tuple[Callable, Dict[str, Any]]]:
        yield self.puzzle, {
            "description": "Add a puzzle",
            "connector": {"title": "puzzle_title"},
            "options": [
                {
                    "name": "title",
                    "description": "Title of the puzzle including whatever characters",
                    "type": discord_slash.SlashCommandOptionType.STRING,
                    "required": True,
                }
            ],
        }
        yield self.remove, {
            "description": "Remove a puzzle",
            "permissions": {"administrator": True},
            "connector": {"title": "puzzle_title"},
            "options": [
                {
                    "name": "title",
                    "description": "Title of the puzzle including whatever characters",
                    "type": discord_slash.SlashCommandOptionType.STRING,
                    "required": True,
                }
            ],
        }
        yield self.voice, {
            "description": "Toggle voice channel, use in the puzzle's text channel"
        }
        yield self.solve, {
            "description": "Mark a puzzle as solved, use in the puzzle's text channel"
        }

    @property
    def solved_category(self) -> Optional[discord.CategoryChannel]:
        return self.get_category(self.active_guild, self.solved_category_name)

    async def puzzle(self, ctx: discord_slash.SlashContext, puzzle_title: str) -> None:
        response = await ctx.send(f'Creating 🧩 "{puzzle_title}"')
        puzzle_title = puzzle_title.replace("'", "").replace('"', "")
        channel = discord.utils.get(ctx.guild.text_channels, topic=puzzle_title)
        if channel is not None:
            await response.reply(f"There's already a puzzle called {puzzle_title} 🤔")
            await response.add_reaction(THUMBS_DOWN)
            return
        link = self.drive.add_spreadsheet(puzzle_title)
        channel = await self.add_puzzle_text_channel(ctx.guild, puzzle_title)
        link_message = await channel.send(
            f"I found a 📔spreadsheet for this puzzle at {link}"
        )
        await link_message.pin()
        await self.add_voice_channel(ctx.guild, puzzle_title)
        await response.add_reaction(THUMBS_UP)

    async def remove(self, ctx: discord_slash.SlashContext, puzzle_title: str) -> None:
        response = await ctx.send(f'Removing "{puzzle_title}"')
        puzzle_title = puzzle_title.replace("'", "").replace('"', "")
        await self.find_and_remove_voice_channel(response, puzzle_title)
        text_channel = discord.utils.get(ctx.guild.text_channels, topic=puzzle_title)
        if text_channel is not None:
            await text_channel.delete()
        self.drive.remove_spreadsheet(puzzle_title)
        with suppress(discord.errors.NotFound):
            await response.add_reaction(THUMBS_UP)

    async def solve(self, ctx: discord_slash.SlashContext) -> None:
        if not self.is_puzzle_category(ctx.channel.category):
            if self.is_solved_category(ctx.channel.category):
                await ctx.send("Puzzle already solved 🧠", hidden=True)
            else:
                await ctx.send(
                    "This channel is not associated to a puzzle 🤔", hidden=True
                )
            return
        puzzle_title = self.get_puzzle_title(ctx.channel)
        response = await ctx.send(f"Marking {puzzle_title} as ✅solved")
        solved_category = self.solved_category
        if len(solved_category.channels) == 50:
            await response.reply("@@admin The solved category is full! 🈵")
            await response.add_reaction(THUMBS_DOWN)
            return
        await ctx.channel.edit(category=solved_category)
        self.drive.move_spreadsheet_to_solved(puzzle_title)
        await self.find_and_remove_voice_channel(response, puzzle_title)
        await response.add_reaction(THUMBS_UP)

    @classmethod
    async def voice(cls, ctx: discord_slash.SlashContext) -> None:
        text_channel = ctx.channel
        category = text_channel.category
        if not (cls.is_puzzle_category(category) or cls.is_solved_category(category)):
            await ctx.send(
                "A 🔊voice channel can only be toggled in a puzzle's text channel 🤔",
                hidden=True,
            )
            return
        puzzle_title = text_channel.topic.strip()
        response = await ctx.send(
            f"Toggling 🔊voice channel for {puzzle_title}", delete_after=60
        )
        guild = ctx.guild
        voice_channel = discord.utils.get(guild.voice_channels, name=puzzle_title)
        if voice_channel is not None:
            reaction = (
                THUMBS_UP
                if await cls.remove_voice_channel(voice_channel, response)
                else THUMBS_DOWN
            )
        else:
            await cls.add_voice_channel(guild, puzzle_title)
            reaction = THUMBS_UP
        await response.add_reaction(reaction)

    @classmethod
    def run_from_config(cls) -> None:
        config = ConfigParser()
        config.read("config.ini")
        bot = cls(
            drive_root_folder=config["Google drive"]["root folder"],
            guild_id=int(config["discord"]["guild id"]),
        )
        discord_token = config["discord"]["token"]
        bot.run(discord_token)

    async def print_oauth_url(self) -> None:
        data = await self.application_info()
        url = discord.utils.oauth_url(
            data.id,
            permissions=self.required_permissions,
            scopes=("applications.commands", "bot"),
        )
        print(f"Add me to your server: {url}")

    @classmethod
    def get_puzzle_title(cls, text_channel: discord.TextChannel) -> str:
        return text_channel.topic.strip()

    @classmethod
    async def add_voice_channel(
        cls, guild: discord.Guild, name: str
    ) -> discord.VoiceChannel:
        voice_category = cls.get_category(guild, cls.voice_category_name)
        return await guild.create_voice_channel(
            name, category=voice_category, topic=name
        )

    @classmethod
    async def find_and_remove_voice_channel(
        cls, response: discord.Message, name: str
    ) -> None:
        channel = discord.utils.get(response.guild.voice_channels, name=name)
        if channel is not None:
            await cls.remove_voice_channel(channel, response)

    @classmethod
    async def remove_voice_channel(
        cls, voice_channel: discord.VoiceChannel, response: discord.Message
    ) -> bool:
        if voice_channel.members:
            await response.reply("Not removing voice channel in use 🗣️")
            return False
        else:
            await voice_channel.delete()
            return True

    @classmethod
    async def add_puzzle_text_channel(
        cls, guild: discord.Guild, name: str
    ) -> discord.TextChannel:
        puzzle_category = cls.get_category(guild, cls.puzzles_category_name)
        channel = discord.utils.get(guild.text_channels, topic=name)
        if not channel:
            return await guild.create_text_channel(
                name, category=puzzle_category, topic=name
            )
        else:
            return channel

    @classmethod
    def is_puzzle_category(cls, category: Optional[discord.CategoryChannel]) -> bool:
        return cls.category_has_prefix(category, cls.puzzles_category_name)

    @classmethod
    def is_solved_category(cls, category: Optional[discord.CategoryChannel]) -> bool:
        return cls.category_has_prefix(category, cls.solved_category_name)

    @staticmethod
    def get_category(guild: discord.Guild, name: str) -> discord.CategoryChannel:
        category = discord.utils.get(guild.categories, name=name)
        if category is not None:
            return category
        PuzzleBot.create_categories(guild, (name,))
        return PuzzleBot.get_category(guild, name)

    @staticmethod
    async def create_categories(
        guild: discord.Guild, category_iterable: Iterable[str]
    ) -> None:
        for name in category_iterable:
            if discord.utils.get(guild.categories, name=name) is None:
                await guild.create_category(name)

    @staticmethod
    def category_has_prefix(
        category: Optional[discord.CategoryChannel], prefix: str
    ) -> bool:
        return category is not None and category.name.lower().startswith(prefix.lower())


if __name__ == "__main__":
    PuzzleBot.run_from_config()

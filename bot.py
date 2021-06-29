#!/usr/bin/env python3
# coding: utf-8

import os
from typing import Any, Callable, Dict, Iterator, Optional, Tuple, Union

import discord
import discord.ext.commands
import discord_slash
import dotenv
import pydrive.auth
import pydrive.drive


class PuzzleDrive(pydrive.drive.GoogleDrive):
    SAVED_CREDENTIALS_FILE = "drive_credentials.json"

    def __init__(self) -> None:
        dotenv.load_dotenv()
        self.authentication = pydrive.auth.GoogleAuth()
        self.authentication.LoadCredentialsFile(PuzzleDrive.SAVED_CREDENTIALS_FILE)
        if self.authentication.credentials is None:
            self.authentication = self.authenticate()
        self.refresh_drive_token_if_expired()
        super().__init__(self.authentication)
        print("Loaded Google Drive credentials")
        self.drive_root_folder = os.getenv("DRIVE_ROOT_FOLDER")
        self.root_folder_id = self.get_root_folder_id()
        self.solved_folder_id = self.get_solved_folder_id()

    @staticmethod
    def authenticate() -> pydrive.auth.GoogleAuth:
        authorization = pydrive.auth.GoogleAuth()
        authorization.LocalWebserverAuth()
        authorization.SaveCredentialsFile(PuzzleDrive.SAVED_CREDENTIALS_FILE)
        print(f"Google authentication saved to {PuzzleDrive.SAVED_CREDENTIALS_FILE}")
        return authorization

    def get_root_folder_id(self) -> str:
        # could be hardcoded to speed up startup
        default_folder_id = self.ListFile(
            {
                "q": f"mimeType = 'application/vnd.google-apps.folder' and title = "
                f"'{self.drive_root_folder}'"
            }
        ).GetList()[0]["id"]
        return default_folder_id

    def get_solved_folder_id(self) -> str:
        try:
            return self.ListFile(
                {
                    "q": f"mimeType = 'application/vnd.google-apps.folder' and title = 'Solved' and "
                    f"'{self.root_folder_id}' in parents"
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

    def refresh_drive_token_if_expired(self) -> None:
        if self.authentication.access_token_expired:
            self.authentication.Refresh()
            self.authentication.SaveCredentialsFile(self.SAVED_CREDENTIALS_FILE)

    def add_spreadsheet(self, title: str) -> str:
        self.refresh_drive_token_if_expired()
        search_list = self.ListFile(
            {
                "q": f"mimeType = 'application/vnd.google-apps.spreadsheet' and title = '{title}' "
                f"and '{self.root_folder_id}' in parents and trashed = false"
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

    def move_spreadsheet_to_solved(self, title: str) -> None:
        self.refresh_drive_token_if_expired()
        search_list = self.ListFile(
            {
                "q": f"mimeType = 'application/vnd.google-apps.spreadsheet' and title = '{title}' "
                f"and '{self.root_folder_id}' in parents and trashed = false"
            }
        ).GetList()
        for spreadsheet in search_list:
            spreadsheet["parents"] = [
                {"kind": "drive#fileLink", "id": self.solved_folder_id}
            ]
            spreadsheet.Upload()

    async def remove_spreadsheet(self, title: str) -> None:
        for folder in [self.root_folder_id, self.solved_folder_id]:
            search_list = self.ListFile(
                {
                    "q": f"mimeType = 'application/vnd.google-apps.spreadsheet' and title = '{title}' and"
                    f" '{folder}' in parents and trashed = false"
                }
            ).GetList()
            for spreadsheet in search_list:
                spreadsheet.Trash()


class PuzzleBot(discord.ext.commands.Bot):
    description = "A bot to help puzzle hunts"
    puzzles_category_name = "Puzzles"
    solved_category_name = "Solved"

    def __init__(self, guild_id: int, **options: Dict[str, Any]) -> None:
        super().__init__(
            discord.ext.commands.when_mentioned,
            description=self.description,
            intents=self.get_intents(),
            **options,
        )
        self.guild_id = guild_id
        self.drive = PuzzleDrive()
        self.slash_command = discord_slash.SlashCommand(self)

    def get_events(self) -> Iterator[Callable]:
        yield self.on_ready

    async def register_commands_and_events(self) -> None:
        for event in self.get_events():
            self.event(event)
        for command, kwargs in self.get_commands():
            self.slash_command.slash(guild_ids=[self.guild_id], **kwargs)(command)
        try:
            await self.slash_command.sync_all_commands()
        except discord.errors.Forbidden as error:
            print(
                f"I need more permissions: "
                f"https://discord.com/api/oauth2/authorize?client_id={self.user.id}&scope=applications.commands"
            )
            raise error

    async def on_ready(self) -> None:
        print(
            f"Logged in as {self.user.name} (id #{self.user.id}) on {self.active_guild}"
        )
        permissions = self.active_guild.me.guild_permissions
        if permissions < self.required_permissions():
            await self.print_oauth_url()
            exit(1)
        await self.register_commands_and_events()
        await self.make_categories()
        print("------")

    @property
    def active_guild(self) -> discord.Guild:
        return self.get_guild(self.guild_id)

    def get_commands(self) -> Iterator[Tuple[Callable, Dict[str, Any]]]:
        yield self.puzzle, {"description": "Add a puzzle"}
        yield self.remove, {
            "description": "Remove a puzzle",
            "permissions": {"administrator": True},
        }
        yield self.voice, {"description": "Toggle voice channel"}
        yield self.solve, {"description": "Mark a puzzle as solved"}

    async def puzzle(self, ctx: discord_slash.SlashContext, puzzle_title: str) -> None:
        channel = discord.utils.get(ctx.guild.text_channels, topic=puzzle_title)
        if channel is not None:
            await ctx.send("There's already a puzzle channel with this name")
            return
        link = self.drive.add_spreadsheet(puzzle_title)
        channel = await self.add_puzzle_text_channel(ctx, puzzle_title)
        link_message = await channel.send(
            f"I found a spreadsheet for this puzzle at {link}"
        )
        await link_message.pin()
        await self.add_voice_channel(ctx, puzzle_title, check_if_exists=True)
        await ctx.send(content=f'Created puzzle "{puzzle_title}"')

    async def remove(self, ctx: discord_slash.SlashContext, puzzle_title: str) -> None:
        await self.remove_voice_channel(ctx, puzzle_title)
        text_channel = discord.utils.get(ctx.guild.text_channels, topic=puzzle_title)
        if text_channel is not None:
            await text_channel.delete()
        await self.drive.remove_spreadsheet(puzzle_title)
        await ctx.message.add_reaction("👍")

    async def solve(self, ctx: discord_slash.SlashContext) -> None:
        if not self.is_puzzle_category(ctx.channel.category):
            if self.is_solved_category(ctx.channel.category):
                await ctx.send("Puzzle already solved!")
            else:
                await ctx.send("This channel is not associated to a puzzle!")
            return
        puzzle_title = self.get_puzzle_title_from_context(ctx)
        solved_category = self.solved_category(ctx)
        if len(solved_category.channels) == 50:
            await ctx.send("@@admin The solved category is full!")
            return
        self.drive.move_spreadsheet_to_solved(puzzle_title)
        await ctx.channel.edit(category=solved_category)
        await self.remove_voice_channel(ctx, puzzle_title)
        await ctx.send(f"Marked {puzzle_title} as solved")

    def solved_category(self, ctx) -> Optional[discord.CategoryChannel]:
        return self.get_category_by_name(ctx, self.solved_category_name)

    async def print_oauth_url(self) -> None:
        data = await self.application_info()
        url = discord.utils.oauth_url(data.id, permissions=self.required_permissions())
        print(f"Add me to your server: {url}")

    @classmethod
    def required_permissions(cls) -> discord.Permissions:
        return discord.Permissions(
            add_reactions=True,
            embed_links=True,
            manage_channels=True,
            manage_messages=True,
            read_messages=True,
            send_messages=True,
            view_channel=True,
            use_slash_commands=True,
        )

    @classmethod
    def get_intents(cls) -> discord.Intents:
        intents = discord.Intents.default()
        return intents

    @classmethod
    async def voice(cls, ctx: discord_slash.SlashContext) -> None:
        category = ctx.channel.category
        if not (cls.is_puzzle_category(category) or cls.is_solved_category(category)):
            await ctx.send(
                "Voice channels can only be toggled from the corresponding text channel!"
            )
            return
        puzzle_title = ctx.channel.topic.strip()
        if await cls.toggle_puzzle_voice_channel(ctx, puzzle_title):
            await ctx.send(f"Toggled voice channel for {puzzle_title}", delete_after=60)

    @classmethod
    def get_puzzle_title_from_context(cls, ctx: discord_slash.SlashContext) -> str:
        return ctx.channel.topic.strip()

    @classmethod
    async def toggle_puzzle_voice_channel(
        cls, ctx: discord_slash.SlashContext, name: str
    ) -> bool:
        channel = discord.utils.get(ctx.guild.voice_channels, name=name)
        if not channel:
            await cls.add_voice_channel(ctx, name)
            return True
        else:
            return await cls.remove_voice_channel(ctx, name)

    @classmethod
    async def add_voice_channel(
        cls, ctx: discord_slash.SlashContext, name: str, check_if_exists: bool = False
    ) -> discord.VoiceChannel:
        if check_if_exists:
            voice_channel = discord.utils.get(ctx.guild.voice_channels, name=name)
            if voice_channel:
                await ctx.send(f"Voice channel with name '{name}' already exists")
                return voice_channel
        voice_category = cls.get_category_by_name(ctx, "Puzzle Voice Channels")
        return await ctx.guild.create_voice_channel(
            name, category=voice_category, topic=name
        )

    @classmethod
    async def remove_voice_channel(
        cls, ctx: discord_slash.SlashContext, name: str
    ) -> bool:
        channel = discord.utils.get(ctx.guild.voice_channels, name=name)
        if channel is None:
            return False
        if channel.members:
            await ctx.send("Not removing voice channel in use")
            return False
        else:
            await channel.delete()
            return True

    @classmethod
    async def add_puzzle_text_channel(
        cls, ctx: discord_slash.SlashContext, name: str
    ) -> discord.TextChannel:
        puzzle_category = cls.get_category_by_name(ctx, cls.puzzles_category_name)
        channel = discord.utils.get(ctx.guild.text_channels, topic=name)
        if not channel:
            return await ctx.guild.create_text_channel(
                name, category=puzzle_category, topic=name
            )
        else:
            return channel

    @classmethod
    def get_category_by_name(
        cls, ctx: Union[discord_slash.SlashContext, discord.Guild], name: str
    ) -> Optional[discord.CategoryChannel]:
        return discord.utils.get(ctx.categories, name=name)

    @classmethod
    def is_puzzle_category(cls, category: Optional[discord.CategoryChannel]) -> bool:
        return cls.category_has_prefix(category, cls.puzzles_category_name)

    @classmethod
    def is_solved_category(cls, category: Optional[discord.CategoryChannel]) -> bool:
        return cls.category_has_prefix(category, cls.solved_category_name)

    @staticmethod
    def category_has_prefix(
        category: Optional[discord.CategoryChannel], prefix: str
    ) -> bool:
        return category is not None and category.name.lower().startswith(prefix.lower())

    async def make_categories(self) -> None:
        for category in self.puzzles_category_name, self.solved_category_name:
            if self.get_category_by_name(self.active_guild, category) is None:
                await self.active_guild.create_category(category)


if __name__ == "__main__":
    dotenv.load_dotenv()
    discord_token = os.getenv("DISCORD_TOKEN")
    bot = PuzzleBot(guild_id=int(os.getenv("DISCORD_GUILD_ID")))
    bot.run(discord_token)

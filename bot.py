#!/usr/bin/env python3
# coding: utf-8

import os
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

import discord
import discord.ext.commands
from discord_slash import SlashCommand, SlashContext
from dotenv import load_dotenv
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive


class PuzzleDrive(GoogleDrive):
    SAVED_CREDENTIALS_FILE = "drive_credentials.json"

    def __init__(self) -> None:
        load_dotenv()
        self.authentication = GoogleAuth()
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
    def authenticate() -> GoogleAuth:
        authorization = GoogleAuth()
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

    def __init__(self, guild_id: int, **options: Dict[str, Any]) -> None:
        super().__init__(
            discord.ext.commands.when_mentioned,
            description=self.description,
            intents=self.get_intents(),
            **options,
        )
        self.guild_id = guild_id
        self.drive = PuzzleDrive()
        self.slash_command = SlashCommand(self)

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
                f"Give me more permissions: "
                f"https://discord.com/api/oauth2/authorize?client_id={self.user.id}&scope=applications.commands"
            )
            raise error

    async def on_ready(self) -> None:
        print(
            f"Logged in as {self.user.name} ({self.user.id}) on {self.get_guild(self.guild_id)}"
        )
        permissions = self.get_guild(self.guild_id).me.guild_permissions
        if permissions < self.get_permissions():
            await self.print_oauth_url()
            exit(1)
        await self.register_commands_and_events()
        print("------")

    def get_commands(self) -> Iterator[Tuple[Callable, Dict[str, Any]]]:
        yield self.puzzle, {"description": "Add a puzzle"}
        yield self.remove, {
            "description": "Remove a puzzle",
            "permissions": {"administrator": True},
        }
        yield self.voice, {"description": "Toggle voice channel"}
        yield self.solve, {"description": "Mark a puzzle as solved"}

    async def puzzle(self, ctx: SlashContext, puzzle_title: str) -> None:
        """Adds a puzzle

        Creates channels and spreadsheets associated to a new puzzle.

        Usage: @DonnerBot p[uzzle] Multi Word Puzzle Title"""
        if not puzzle_title:
            await ctx.send(
                "Please include puzzle name as argument when creating a puzzle"
            )
            return
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

    async def remove(
        self, ctx: SlashContext, *multi_word_title: str
    ) -> Optional[discord.Message]:
        """Removes puzzle channels and spreadsheets

        Removes all channels and spreadsheets associated with the puzzle title. Only available with administrator
        permissions on the server. Does not have an abbreviated form for safety reasons. Use with caution!

        Usage: @DonnerBot remove Multi Word Puzzle Title"""
        puzzle_title = " ".join(multi_word_title)
        if not puzzle_title:
            return await ctx.send(
                "Please include puzzle name as argument when creating a puzzle"
            )
        await self.remove_voice_channel(ctx, puzzle_title)
        text_channel = discord.utils.get(ctx.guild.text_channels, topic=puzzle_title)
        if text_channel is not None:
            await text_channel.delete()
        await self.drive.remove_spreadsheet(puzzle_title)
        await ctx.message.add_reaction("👍")

    async def solve(self, ctx: SlashContext) -> Optional[discord.Message]:
        """Marks puzzle as solved

        Moves the text channel and spreadsheet (?) associated to a puzzle to solved and removes the associated voice
        channel if empty. Can only be used in the corresponding text channel. Also automatically updates the party size.

        Usage: @DonnerBot s[olve]"""
        if ctx.channel.category.name[:7] != "Puzzles":
            if ctx.channel.category.name == "Solved":
                return await ctx.send("Puzzle already solved!")
            return await ctx.send("This channel is not associated to a puzzle!")
        puzzle_title = self.get_puzzle_title_from_context(ctx)
        solved_category = self.get_category_by_name(ctx, "Solved")
        if len(solved_category.channels) == 50:
            return await ctx.send("@@admin The solved category is full!")
        self.drive.move_spreadsheet_to_solved(puzzle_title)
        await ctx.channel.edit(category=solved_category)
        await self.remove_voice_channel(ctx, puzzle_title)
        await ctx.message.add_reaction("👍")

    async def print_oauth_url(self) -> None:
        data = await self.application_info()
        permissions = self.get_permissions()
        url = discord.utils.oauth_url(data.id, permissions=permissions)
        print(f"Add me to your server: {url}")

    @classmethod
    def get_permissions(cls) -> discord.Permissions:
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
    async def voice(cls, ctx: SlashContext) -> None:
        """Toggles voice channel

        Toggles voice channel on or off for a given puzzle. Does not turn off if currently in use. Can only be used
        in the corresponding text channel.

        Usage: @DonnerBot v[oice]"""
        category_name = ctx.channel.category.name
        if category_name[:7] != "Puzzles" and category_name[:6] != "Solved":
            await ctx.send(
                "Voice channels can only be toggled from the corresponding text channel!"
            )
            return
        puzzle_title = ctx.channel.topic.strip()
        if await cls.toggle_puzzle_voice_channel(ctx, puzzle_title):
            await ctx.message.add_reaction("👍")

    @classmethod
    def get_puzzle_title_from_context(cls, ctx: SlashContext) -> str:
        return ctx.channel.topic.strip()

    @classmethod
    async def toggle_puzzle_voice_channel(cls, ctx: SlashContext, name: str) -> bool:
        channel = discord.utils.get(ctx.guild.voice_channels, name=name)
        if not channel:
            await cls.add_voice_channel(ctx, name)
            return True
        else:
            return await cls.remove_voice_channel(ctx, name)

    @classmethod
    async def add_voice_channel(
        cls, ctx: SlashContext, name: str, check_if_exists: bool = False
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
    async def remove_voice_channel(cls, ctx: SlashContext, name: str) -> bool:
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
        cls, ctx: SlashContext, name: str
    ) -> discord.TextChannel:
        puzzle_category = cls.get_category_by_name(ctx, "Puzzles")
        channel = discord.utils.get(ctx.guild.text_channels, topic=name)
        if not channel:
            return await ctx.guild.create_text_channel(
                name, category=puzzle_category, topic=name
            )
        else:
            return channel

    @classmethod
    def get_category_by_name(
        cls, ctx: SlashContext, name: str
    ) -> discord.CategoryChannel:
        return discord.utils.get(ctx.guild.categories, name=name)


if __name__ == "__main__":
    load_dotenv()
    discord_token = os.getenv("DISCORD_TOKEN")
    bot = PuzzleBot(guild_id=int(os.getenv("DISCORD_GUILD_ID")))
    bot.run(discord_token)

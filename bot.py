#!/usr/bin/env python3
# coding: utf-8
from collections.abc import Coroutine, Iterator, Iterable
from configparser import ConfigParser
from typing import Any

import interactions
import interactions.api
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


class PuzzleBot(interactions.Client):
    description = "A bot to help puzzle hunts"
    puzzles_category_name = "🧩Puzzles"
    solved_category_name = "✅Solved"
    voice_category_name = "🧩Puzzle Voice Channels"

    def __init__(
        self, token: str, guild_id: int, drive_root_folder: str, **options
    ) -> None:
        super().__init__(
            token=token,
            **options,
        )
        self.guild_id = guild_id

        self.drive = PuzzleDrive(drive_root_folder)
        for event in self.events:
            self.event(event)
        for command, options in self.commands:
            self.command(**options)(command)

    @property
    def events(self) -> Iterator[Coroutine]:
        yield self.on_ready

    @property
    def commands(self) -> Iterator[tuple[Coroutine, dict]]:
        yield self.add_puzzle, {
            "name": "puzzle",
            "description": "Add a puzzle",
            "scope": [self.guild_id],
            "options": [
                {
                    "name": "puzzle_title",
                    "description": "Title of the puzzle including whatever characters",
                    "type": interactions.OptionType.STRING,
                    "required": True,
                }
            ],
        }

    @property
    async def channels(self) -> Iterator[interactions.Channel]:
        return [
            interactions.Channel(**data)
            for data in self.http.get_all_channels(self.guild_id)
        ]

    async def on_ready(self) -> None:
        print(f"Logged in as {self.me.name} (id #{self.me.id})")

    async def add_puzzle(self, ctx, puzzle_title: str) -> None:
        response = await ctx.send(f'Creating 🧩 "{puzzle_title}"')
        puzzle_title = puzzle_title.replace("'", "").replace('"', "")

        channel = self.get(await self.channels, topic=puzzle_title)
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
        await response.edit(content=f'Creating 🧩 "{puzzle_title}" at {channel.mention}')
        await response.add_reaction(THUMBS_UP)

    async def get_guild(self) -> interactions.Guild:
        guild_data = await self.http.get_guild(self.guild_id)
        return interactions.Guild(**guild_data)

    async def remove_puzzle(self) -> None:
        pass

    async def solve(self) -> None:
        pass

    @classmethod
    async def voice(cls) -> None:
        pass

    @classmethod
    def run_from_config(cls) -> None:
        config = ConfigParser()
        config.read("config.ini")
        bot = cls(
            token=config["discord"]["token"],
            drive_root_folder=config["Google drive"]["root folder"],
            guild_id=int(config["discord"]["guild id"]),
        )
        bot.start()

    @staticmethod
    def get(iterable: Iterable, **parameters: Any) -> Any:
        print(parameters)
        for item in iterable:
            if all(getattr(item, name) == value for name, value in parameters.items()):
                return item
        return None

    def add_puzzle_text_channel(
        self, guild: interactions.api.models.Guild, puzzle_title: str
    ) -> interactions.Channel:
        puzzle_category_id = self.puzzle_category(guild)
        return await guild.create_channel(
            name=puzzle_title,
            type=interactions.api.models.channel.ChannelType.GUILD_TEXT,
            topic=puzzle_title,
            parent_id=puzzle_category_id,
        )

    @property
    def puzzle_category(self, guild):
        return cls.get_category(guild, "🧩Puzzles")


class DonnerBot(PuzzleBot):
    description = "A bot to help the Donner Party hunt."


if __name__ == "__main__":
    DonnerBot.run_from_config()

#!/usr/bin/env python3
# coding: utf-8
from configparser import ConfigParser
from contextlib import suppress
from typing import Any, Callable, Dict, Iterable, Iterator, Optional, Tuple

import interactions
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

    def __init__(self, **options) -> None:
        super().__init__(**options)

    async def on_ready(self) -> None:
        pass

    async def add_puzzle(self) -> None:
        pass

    async def remove_puzzle(self) -> None:
        pass

    async def solve(self) -> None:
        pass

    @classmethod
    async def voice(cls) -> None:
        pass

    @classmethod
    def run_from_config(cls) -> None:
        pass


class DonnerBot(PuzzleBot):
    description = "A bot to help the Donner Party hunt."


if __name__ == "__main__":
    DonnerBot.run_from_config()

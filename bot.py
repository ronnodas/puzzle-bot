#!/usr/bin/env python3
# coding: utf-8

import asyncio
import os
from typing import Optional

import discord
from discord.ext import commands
from dotenv import load_dotenv
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD = os.getenv('DISCORD_GUILD')
DRIVE_ROOT_FOLDER_NAME = os.getenv('DRIVE_ROOT_FOLDER')

SAVED_CREDENTIALS_FILE = "saved_credentials.json"

intents = discord.Intents.default()
intents.members = True
intents.messages = True

description = "A bot to help the Donner Party hunt."
help_command = commands.DefaultHelpCommand(no_category='Commands')

bot = commands.Bot(commands.when_mentioned, description=description, intents=intents, help_command=help_command)


def get_category_by_name(ctx: discord.Member, name: str) -> discord.CategoryChannel:
    return discord.utils.get(ctx.guild.categories, name=name)


def get_party_channel(ctx: discord.Member) -> discord.TextChannel:
    for channel in ctx.guild.text_channels:
        if channel.name.startswith("party-of"):
            return channel


def get_party_count(ctx: discord.Member) -> int:
    solved_category = get_category_by_name(ctx, "Solved")
    solved_number = len(solved_category.channels)
    for i in range(2, 10):
        solved_category = get_category_by_name(ctx, f"Solved {i}")
        if solved_category is None:
            break
        solved_number += len(solved_category.channels)
    return len(ctx.guild.members) - solved_number


async def add_puzzle_text_channel(ctx: discord.Member, name: str) -> discord.TextChannel:
    puzzle_category = get_category_by_name(ctx, "Puzzles")
    channel = discord.utils.get(ctx.guild.text_channels, topic=name)
    if not channel:
        return await ctx.guild.create_text_channel(name, category=puzzle_category, topic=name)
    else:
        return channel


async def remove_voice_channel(ctx: discord.Member, name: str) -> bool:
    channel = discord.utils.get(ctx.guild.voice_channels, name=name)
    if channel is None:
        return False
    if channel.members:
        await ctx.send("Not removing voice channel in use")
        return False
    else:
        await channel.delete()
        return True


async def add_voice_channel(ctx: discord.Member, name: str, check_if_exists: bool = False) -> discord.VoiceChannel:
    if check_if_exists:
        voice_channel = discord.utils.get(ctx.guild.voice_channels, name=name)
        if voice_channel:
            await ctx.send(f"Voice channel with name '{name}' already exists")
            return voice_channel
    voice_category = get_category_by_name(ctx, "Puzzle Voice Channels")
    return await ctx.guild.create_voice_channel(name, category=voice_category, topic=name)


async def toggle_puzzle_voice_channel(ctx: discord.Member, name: str) -> bool:
    channel = discord.utils.get(ctx.guild.voice_channels, name=name)
    if not channel:
        await add_voice_channel(ctx, name)
        return True
    else:
        return await remove_voice_channel(ctx, name)


async def update_party_size_passively(ctx: discord.Member) -> int:
    party_channel = get_party_channel(ctx)
    n = get_party_count(ctx)
    if n >= 0:
        num = str(n)
    else:
        num = "minus" + str(n)
    await party_channel.edit(name=("party-of-" + num))
    return n


def add_spreadsheet(title: str) -> str:
    refresh_drive_token_if_expired()
    # TODO: also check solved?
    search_list = drive.ListFile({'q': f"mimeType = 'application/vnd.google-apps.spreadsheet' and title = '{title}' "
                                       f"and '{default_folder_id}' in parents and trashed = false"}).GetList()
    if search_list:
        print(search_list)
        return search_list[0]['alternateLink']
    spreadsheet = drive.CreateFile({'title': title,
                                    'parents': [{'id': default_folder_id}],
                                    'mimeType': 'application/vnd.google-apps.spreadsheet'})
    spreadsheet.Upload()
    spreadsheet.FetchMetadata()
    return spreadsheet['alternateLink']


def move_spreadsheet_to_solved(title: str) -> None:
    refresh_drive_token_if_expired()
    search_list = drive.ListFile({'q': f"mimeType = 'application/vnd.google-apps.spreadsheet' and title = '{title}' "
                                       f"and '{default_folder_id}' in parents and trashed = false"}).GetList()
    for spreadsheet in search_list:
        spreadsheet['parents'] = [{'kind': 'drive#fileLink', 'id': solved_folder_id}]
        spreadsheet.Upload()


def refresh_drive_token_if_expired() -> None:
    if google_authentication.access_token_expired:
        google_authentication.Refresh()
        google_authentication.SaveCredentialsFile(SAVED_CREDENTIALS_FILE)


@bot.event
async def on_member_join(member: discord.Member) -> None:
    party_channel = get_party_channel(member)
    n = await update_party_size_passively(member)
    name = member.nick if member.nick is not None else member.name
    message = await party_channel.send(f"{name} has joined! We're now Donner, Party of {n}!")
    await message.add_reaction('😃')


@bot.event
async def on_member_remove(member: discord.Member) -> None:
    party_channel = get_party_channel(member)
    n = await update_party_size_passively(member)
    name = member.nick if member.nick is not None else member.name
    message = await party_channel.send(f"{name} has left️! We're now Donner, Party of {n}!")
    await message.add_reaction('☹')


@bot.event
async def on_ready() -> None:
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')


@bot.command(aliases=['p'])
async def puzzle(ctx: discord.Member, *multi_word_title: str) -> Optional[discord.Message]:
    """Adds a puzzle

    Creates channels and spreadsheets associated to a new puzzle.

    Usage: @DonnerBot p[uzzle] Multi Word Puzzle Title"""
    puzzle_title = ' '.join(multi_word_title)
    puzzle_title = ''.join(c for c in puzzle_title if c != "'")
    if not puzzle_title:
        return await ctx.send("Please include puzzle name as argument when creating a puzzle")
    channel = discord.utils.get(ctx.guild.text_channels, topic=puzzle_title)
    if channel is not None:
        return await ctx.send("There's already a puzzle channel with this name")
    link = add_spreadsheet(puzzle_title)
    channel = await add_puzzle_text_channel(ctx, puzzle_title)
    link_message = await channel.send(f"I found a spreadsheet for this puzzle at {link}")
    await link_message.pin()
    await add_voice_channel(ctx, puzzle_title, check_if_exists=True)
    await ctx.message.add_reaction('👍')


@bot.command()
@commands.has_permissions(administrator=True)
async def remove(ctx: discord.Member, *multi_word_title: str) -> Optional[discord.Message]:
    """Removes puzzle channels and spreadsheets

    Removes all channels and spreadsheets associated with the puzzle title. Only available with administrator
    permissions on the server. Does not have an abbreviated form for safety reasons. Use with caution!

    Usage: @DonnerBot remove Multi Word Puzzle Title"""
    puzzle_title = ' '.join(multi_word_title)
    if not puzzle_title:
        return await ctx.send("Please include puzzle name as argument when creating a puzzle")
    await remove_voice_channel(ctx, puzzle_title)
    text_channel = discord.utils.get(ctx.guild.text_channels, topic=puzzle_title)
    if text_channel is not None:
        await text_channel.delete()
    for folder in [default_folder_id, solved_folder_id]:
        search_list = drive.ListFile(
            {'q': f"mimeType = 'application/vnd.google-apps.spreadsheet' and title = '{puzzle_title}' and '{folder}' "
                  f"in parents and trashed = false"}).GetList()
        for spreadsheet in search_list:
            spreadsheet.Trash()
    await ctx.message.add_reaction('👍')


@bot.command(aliases=['v'])
async def voice(ctx: discord.Member) -> None:
    """Toggles voice channel

    Toggles voice channel on or off for a given puzzle. Does not turn off if currently in use. Can only be used
    in the corresponding text channel.

    Usage: @DonnerBot v[oice]"""
    category_name = ctx.channel.category.name
    if category_name[:7] != "Puzzles" and category_name[:6] != "Solved":
        await ctx.send("Voice channels can only be toggled from the corresponding text channel!")
        return
    puzzle_title = ctx.channel.topic.strip()
    if await toggle_puzzle_voice_channel(ctx, puzzle_title):
        await ctx.message.add_reaction('👍')


@bot.command(aliases=['s'])
async def solve(ctx: discord.Member) -> Optional[discord.Message]:
    """Marks puzzle as solved

    Moves the text channel and spreadsheet (?) associated to a puzzle to solved and removes the associated voice
    channel if empty. Can only be used in the corresponding text channel. Also automatically updates the party size.

    Usage: @DonnerBot s[olve]"""
    if ctx.channel.category.name[:7] != "Puzzles":
        if ctx.channel.category.name == "Solved":
            return await ctx.send("Puzzle already solved!")
        return await ctx.send("This channel is not associated to a puzzle!")
    puzzle_title = ctx.channel.topic.strip()
    solved_category = get_category_by_name(ctx, "Solved")
    if len(solved_category.channels) == 50:
        return await ctx.send("@@admin The solved category is full!")
    move_spreadsheet_to_solved(puzzle_title)
    await ctx.channel.edit(category=solved_category)
    await remove_voice_channel(ctx, puzzle_title)
    await asyncio.sleep(0.3)
    count = await update_party_size_passively(ctx)
    await get_party_channel(ctx).send(
        f"Solved puzzle {puzzle_title}. We're now Donner, Party of {count}...")
    await ctx.message.add_reaction('👍')


@bot.command(name="recount", aliases=['r'])
async def update_party_size(ctx: discord.Member) -> None:
    """Updates party size

    Updates the party size count should it get out of sync for whatever reason. Actually renames the topmost
    channel whose name starts with 'party-of-'.

    Usage: @DonnerBot r[ecount]"""
    await update_party_size_passively(ctx)
    await ctx.message.add_reaction('👍')


google_authentication = GoogleAuth()
google_authentication.LoadCredentialsFile(SAVED_CREDENTIALS_FILE)
if google_authentication.credentials is None:
    print("Saved credentials not found. Generate using 'authenticator.py'")
    exit(1)
refresh_drive_token_if_expired()
drive = GoogleDrive(google_authentication)
print("Loaded Google Drive credentials")

# could be hardcoded to speed up startup
default_folder_id = drive.ListFile({'q': f"mimeType = 'application/vnd.google-apps.folder' and title = "
                                         f"'{DRIVE_ROOT_FOLDER_NAME}'"}).GetList()[0]['id']
try:
    solved_folder_id = drive.ListFile({'q': f"mimeType = 'application/vnd.google-apps.folder' and title = 'Solved' and "
                                            f"'{default_folder_id}' in parents"}).GetList()[0]['id']
except IndexError:
    solved_folder = drive.CreateFile({'title': 'Solved', 'parents': [{'id': default_folder_id}],
                                      'mimeType': 'application/vnd.google-apps.folder'})
    solved_folder.Upload()
    solved_folder.FetchMetadata()
    solved_folder_id = solved_folder['id']
# end of could be hardcoded

bot.run(TOKEN)

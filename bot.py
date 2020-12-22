#!/usr/bin/env python3
# coding: utf-8

import asyncio
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD = os.getenv('DISCORD_GUILD')

intents = discord.Intents.default()
intents.members = True
intents.messages = True

description = "A bot to help the Donner Party hunt."
help_command = commands.DefaultHelpCommand(
    no_category='Commands'
)

bot = commands.Bot(commands.when_mentioned, description=description, intents=intents, help_command=help_command)


def get_category_by_name(ctx, name):
    return discord.utils.get(ctx.guild.categories, name=name)


def get_party_channel(ctx):
    for channel in ctx.guild.text_channels:
        if channel.name.startswith("party-of"):
            return channel


def get_party_count(ctx):
    solved_category = get_category_by_name(ctx, "Solved")
    return len(ctx.guild.members) - len(solved_category.channels)


async def add_puzzle_text_channel(ctx, name):
    puzzle_category = get_category_by_name(ctx, "Puzzles")
    channel = discord.utils.get(ctx.guild.text_channels, topic=name)
    if not channel:
        await ctx.guild.create_text_channel(name, category=puzzle_category, topic=name)


async def remove_voice_channel(ctx, name):
    channel = discord.utils.get(ctx.guild.voice_channels, name=name)
    if channel is None:
        return
    if not channel.members:
        await ctx.send("Not removing voice channel in use")
    else:
        await channel.delete()
        await ctx.message.add_reaction('👍')


async def toggle_puzzle_voice_channel(ctx, name):
    voice_category = get_category_by_name(ctx, "Voice Channels")
    channel = discord.utils.get(ctx.guild.voice_channels, name=name)
    if not channel:
        await ctx.guild.create_voice_channel(name, category=voice_category, topic=name)
        await ctx.message.add_reaction('👍')
    else:
        await remove_voice_channel(ctx, name)


@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')


@bot.command()
async def puzzle(ctx, *multi_word_title):
    """Adds a puzzle

    Creates channels and spreadsheets (?) associated to a new puzzle.

    Usage: @DonnerBot puzzle Hello World"""
    puzzle_title = ' '.join(multi_word_title)
    if not puzzle_title:
        await ctx.send("Please include puzzle name as argument when creating a puzzle")
        return
    await add_puzzle_text_channel(ctx, puzzle_title)
    await toggle_puzzle_voice_channel(ctx, puzzle_title)
    await ctx.message.add_reaction('👍')


@bot.command()
async def voice(ctx):
    """Toggles voice channel

    Toggles voice channel on or off for a given puzzle. Does not turn off if currently in use. Can only be used
    in the corresponding text channel.

    Usage: @DonnerBot voice"""
    category_name = ctx.channel.category.name
    if category_name != "Puzzles" and category_name != "Solved":
        await ctx.send("Voice channels can only be toggled from the corresponding text channel!")
        return
    puzzle_title = ctx.channel.topic.strip()
    await toggle_puzzle_voice_channel(ctx, puzzle_title)


@bot.command()
async def solve(ctx):
    """Marks puzzle as solved

    Moves the text channel and spreadsheet (?) associated to a puzzle to solved and removes the associated voice
    channel if empty. Can only be used in the corresponding text channel. Also automatically updates the party size.

    Usage: @DonnerBot solve"""
    if ctx.channel.category.name != "Puzzles":
        await ctx.send("Only text channels for unsolved puzzles can be solved!")
        return
    puzzle_title = ctx.channel.topic.strip()
    solved_category = get_category_by_name(ctx, "Solved")
    await ctx.channel.edit(category=solved_category)
    await remove_voice_channel(ctx, puzzle_title)
    await asyncio.sleep(0.3)
    await update_party_size(ctx)
    await get_party_channel(ctx).send(
        f"Solved puzzle {puzzle_title}. We're now Donner, Party of {get_party_count(ctx)}...")


@bot.command(name="recount")
async def update_party_size(ctx):
    """Updates party size

    Updates the party size count should it get out of sync for whatever reason. Actually renames the topmost
    channel whose name starts with 'party-of-'.

    Usage: @DonnerBot recount"""
    channel = get_party_channel(ctx)
    n = get_party_count(ctx)
    if n >= 0:
        num = str(n)
    else:
        num = "minus" + str(n)
    await channel.edit(name=("party-of-" + num))


bot.run(TOKEN)

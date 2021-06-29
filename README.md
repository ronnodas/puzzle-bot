# README #

This is a discord bot for helping with puzzle hunts, with Google Drive integration.

### Initial setup ###
1. Install dependencies from `requirements.txt`, e.g. by running `pip3 install -r requirements.txt`
1. Obtain `client_secrets.json` and place it in your working directory, as in https://pythonhosted.org/PyDrive/quickstart.html#authentication
1. Create an application in https://discord.com/developers/applications and make sure it has the following permissions:
   * 
1. Fill in `.env` (see `.env.example` for syntax)
    1. `DISCORD_TOKEN`:  and put the token here; see https://discordpy.readthedocs.io/en/stable/discord.html  
    1. `DRIVE_ROOT_FOLDER` should be the name of the folder in a Google Drive that the bot will have access to

### Running the bot ###
1. Run `bot.py`, by making it executable or with `python3 bot.py`
1. On first run (and depending on how long since it was last run) it will ask to be given access to a Google Drive account. Make sure there is a folder with the name from 3.ii above.
# README #

This is a discord bot for helping with puzzle hunts, with Google Drive integration. Runs on python 3.6+

## Initial setup ##
1. Install dependencies from `requirements.txt`, eg by running `pip3 install -r requirements.txt`.
1. Create a Google Drive API project on https://console.cloud.google.com/cloud-resource-manager, 
   obtain `client_secrets.json` and place it in the working directory 
   (see https://pythonhosted.org/PyDrive/quickstart.html#authentication).
1. Create an application in https://discord.com/developers/applications and obtain the application *token*, 
   to include in the `.env` file in the next step
   (see https://discordpy.readthedocs.io/en/stable/discord.html).
1. Copy `.env.example.` to `.env` and fill in the fields with appropriate data:
    * `DISCORD_TOKEN`: the discord application token from the previous step
    * `DISCORD_GUILD_ID`: the id for the discord server that the bot is supposed to run on 
      (open discord in browser and look at the url or use *Developer Mode*)
    * `DRIVE_ROOT_FOLDER`: the name of the folder to store the spreadsheets in a Google Drive 
      that the bot will have access to

## Running the bot ##
1. Run `donnerbot.py`, either by making it executable or with `python3 donnerbot.py`.
1. If it outputs a link or opens your browser then follow that link to authenticate the bot 
   and give it the required permissions. Most of these should be one time, on first run.
1. Rerun the bot if it crashes.
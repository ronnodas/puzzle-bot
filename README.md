# README #

This is a discord bot for helping with puzzle hunts, with Google Drive integration. Runs on python 3.6+

## Initial setup ##
1. Install dependencies from `requirements.txt`, eg by running `pip3 install -r requirements.txt`.
2. Create a Google Drive API project on https://console.cloud.google.com/cloud-resource-manager, 
   obtain `client_secrets.json` and place it in the working directory 
   (see https://pythonhosted.org/PyDrive/quickstart.html#authentication).
3. Create an application in https://discord.com/developers/applications and obtain the application *token*, 
   to include in `config.ini` on the next step
   (see https://discordpy.readthedocs.io/en/stable/discord.html).
4. Copy `example-config.ini` to `config.ini` and fill in the fields with appropriate data:
    * `[discord] > token`: the discord application token from the previous step
    * `[discord] > guild id`: the id for the discord server that the bot will to run on 
      (open discord in browser and look at the url or use *Developer Mode*)
    * `[Google Drive] > root folder`: the name of the folder to store the spreadsheets in a Google Drive 
      that the bot will have access to

## Running the bot ##
1. Run `bot.py`, either by making it executable or with `python3 bot.py`.
2. If it outputs a link or opens your browser then follow that link to authenticate the bot 
   and give it the required permissions. Most of these should be one time, on first run.
3. On later runs, if need to reauthorize to google drive then first revoke access and then reauthorize, see https://stackoverflow.com/questions/38467374/google-api-refresh-token-null-and-how-to-refresh-access-token
4. Rerun the bot if it crashes.
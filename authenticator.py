#!/usr/bin/env python3
# coding: utf-8

from pydrive.auth import GoogleAuth

authorization = GoogleAuth()
authorization.LocalWebserverAuth()
authorization.SaveCredentialsFile("saved_credentials.json")
print("Saved to 'saved_credentials.json'")

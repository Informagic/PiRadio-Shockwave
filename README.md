PiRadio (Shoutcast Version)
===========================

<i>Attention:</i> As of 2016-06-27, This repository is no longer actively maintained by me. The code base is sufficient to make it work, though.

This is a fork of Adafruit's Python-WiFi-Radio. Since there's no access to Pandora from Europe, the actual player part of the radio had to be rewritten to allow playing Shoutcast-conform radio streams.

The original Python-WiFi-Radio code was extended in the following ways:
• pushing the select button opens a main menu
• functionality such as play/pause was moved into the menu
• different playlists (each containing various streams) were realized to accomodate for the needs of different users and/or topics
• weather information is accessible over the menu

The streams are stored in simple CSV files that are named following following the convention that a certain part of the file name determines the user/topic/etc. under which the playlist is available in the main menu.

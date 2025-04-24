# Kick to Twitch Chat Converter

A Python script that converts Kick chat messages (obtained from https://kicklet.app/chat-downloader) into [TwitchDownloader](https://github.com/lay295/TwitchDownloader)-compatible chat JSON format, including emote handling and caching.

## Features

- Converts Kick chat messages to Twitch format
- Downloads and embeds emotes with proper base64 encoding
- Handles both static and animated emotes
- Supports emote resizing (including animated GIFs via FFmpeg)
- Implements emote caching to avoid redundant downloads
- Preserves message timing and structure

## Requirements

- Python 3.8+
- Required packages:
  - `requests`
  - `Pillow` (PIL)
- Optional (for GIF resizing):
  - `ffmpeg` (must be in PATH or specified)

## Installation

1. Clone the repository or download the script
2. Install dependencies:
   ```bash
   pip install requests pillow
   ```

## Usage

Basic conversion:
```bash
python kick_chat_to_twitch_converter.py input_kick.json output_twitch.json
```

Advanced options:
```bash
python kick_chat_to_twitch_converter.py input_kick.json output_twitch.json \
    --cache-folder ./emote_cache \
    --max-size 56 \
    --ffmpeg-path `which ffmpeg`
```

### Command Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `input` | Input Kick JSON file | Required |
| `output` | Output Twitch JSON file | Required |
| `--cache-folder` | Folder to cache downloaded emotes | None |
| `--no-save-cache` | Disable saving emotes to cache | False |
| `--ffmpeg-path` | Custom path to ffmpeg executable | 'ffmpeg' |
| `--max-size` | Max size (width/height) for emotes in pixels | None |

## Input Format

The script expects a JSON file containing an array of Kick chat messages in the following format:
```json
[
  {
    "content": "Haha [emote:39250:BBooomer]",
    "createdAt": "2025-04-19T15:32:40Z",
    "userId": 42657070,
    "username": "mrChatter"
  }
]
```

## Output Format

The script generates a [TwitchDownloader](https://github.com/lay295/TwitchDownloader)-compatible chat JSON file containing:
- Original messages with timing preserved
- Embedded emote data in base64
- Proper message structure for [TwitchDownloader chatrender](https://github.com/lay295/TwitchDownloader/blob/master/TwitchDownloaderCLI/README.md#arguments-for-mode-chatrender) command

## License

This project is provided as-is without warranty. You are free to modify and distribute it according to your needs.

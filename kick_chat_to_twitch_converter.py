import argparse
import base64
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from io import BytesIO

import requests
from PIL import Image, ImageSequence

# Cache for downloaded emotes {emote_id: emote_data}
emote_cache = {}

# Track emotes already added to embeddedData {emote_id: {"id": emote_id, "name": emote_name, "uuid": emote_uuid}}
added_emotes = {}


def get_cache_filename(emote_id):
    """Generate a consistent cache filename for an emote"""
    return f"emote_{hashlib.md5(emote_id.encode()).hexdigest()}.json"


def load_cache_from_folder(cache_folder):
    """Load cached emotes from a folder"""
    if not os.path.exists(cache_folder):
        os.makedirs(cache_folder)
        return

    for filename in os.listdir(cache_folder):
        if filename.startswith("emote_") and filename.endswith(".json"):
            try:
                with open(os.path.join(cache_folder, filename), 'r') as f:
                    data = json.load(f)
                    emote_id = data.get("emote_id")
                    if emote_id:
                        emote_cache[emote_id] = data
            except Exception as e:
                print(f"Error loading cache file {filename}: {e}")


def save_emote_to_cache(emote_id, emote_data, cache_folder):
    """Save emote data to cache folder"""
    if not cache_folder:
        return

    cache_file = os.path.join(cache_folder, get_cache_filename(emote_id))
    try:
        data_to_save = emote_data.copy()
        data_to_save["emote_id"] = emote_id
        with open(cache_file, 'w') as f:
            json.dump(data_to_save, f)
    except Exception as e:
        print(f"Error saving emote {emote_id} to cache: {e}")


def resize_with_ffmpeg(input_path, output_path, max_size, ffmpeg_path='ffmpeg'):
    """Resize a GIF using ffmpeg with transparency support"""
    try:
        cmd = [
            ffmpeg_path,
            '-i', input_path,
            '-vf',
            f'scale={max_size}:-1:flags=lanczos,split[s0][s1];[s0]palettegen=reserve_transparent=1[p];'
            '[s1][p]paletteuse=alpha_threshold=128',
            '-f', 'gif',
            '-y',
            output_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except subprocess.CalledProcessError as e:
        stderr_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
        print(f"FFmpeg error: {stderr_msg}")
        return False
    except Exception as e:
        print(f"Error in resize_with_ffmpeg: {str(e)}")
        return False


def download_emote(emote_id, cache_folder=None, no_save_cache=False, ffmpeg_path='ffmpeg', max_size=None):
    if emote_id in emote_cache:
        return emote_cache[emote_id]

    url = f"https://files.kick.com/emotes/{emote_id}/fullsize"
    try:
        emote_name = added_emotes.get(emote_id, {}).get("name", "unnamed")
        print(f"Downloading emote: {emote_name} (ID: {emote_id})")
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        img = Image.open(BytesIO(response.content))
        img_format = img.format or 'PNG'
        is_gif = img_format.upper() == 'GIF'
        target_size = max_size if max_size is not None else max(img.size)
        is_animated = False

        if is_gif:
            try:
                img.seek(1)
                is_animated = True
                img.seek(0)
            except EOFError:
                is_animated = False

        if is_gif and is_animated:
            with tempfile.NamedTemporaryFile(suffix='.gif', delete=False) as temp_input:
                temp_input.write(response.content)
                temp_input_path = temp_input.name

            with tempfile.NamedTemporaryFile(suffix='.gif', delete=False) as temp_output:
                temp_output_path = temp_output.name

            try:
                if max_size is not None and not resize_with_ffmpeg(
                    temp_input_path, temp_output_path, target_size, ffmpeg_path
                ):
                    raise Exception("FFmpeg resize failed")

                with open(temp_output_path if max_size is not None else temp_input_path, 'rb') as f:
                    resized_gif = f.read()

                with Image.open(BytesIO(resized_gif)) as img_check:
                    width, height = img_check.size
                    if img_check.mode != 'P' or 'transparency' not in img_check.info:
                        print(f"Warning: Transparency may not be preserved for emote {emote_name}")

                img_base64 = base64.b64encode(resized_gif).decode('utf-8')
                result = {
                    "data": img_base64,
                    "width": width,
                    "height": height,
                    "mime_type": "image/gif",
                    "is_animated": True
                }
            finally:
                try:
                    os.unlink(temp_input_path)
                    os.unlink(temp_output_path)
                except Exception:
                    pass
        else:
            width, height = img.size
            if max_size is not None and (width > target_size or height > target_size):
                ratio = min(target_size / width, target_size / height)
                new_size = (math.floor(width * ratio), math.floor(height * ratio))
                img = img.resize(new_size, Image.LANCZOS)
                width, height = new_size

            buffered = BytesIO()
            save_format = 'PNG' if is_gif else img_format
            img.save(buffered, format=save_format)
            buffered.seek(0)
            img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

            result = {
                "data": img_base64,
                "width": width,
                "height": height,
                "mime_type": "image/gif" if is_gif else f"image/{save_format.lower()}",
                "is_animated": False
            }

        emote_cache[emote_id] = result
        if cache_folder and not no_save_cache:
            save_emote_to_cache(emote_id, result, cache_folder)

        return result

    except Exception as e:
        print(f"Error downloading emote {emote_name} (ID: {emote_id}): {str(e)}")
        return None


def parse_kick_message(content):
    fragments = []
    emoticons = []
    parts = []
    remaining = content

    while True:
        start = remaining.find('[emote:')
        if start == -1:
            break
        end = remaining.find(']', start)
        if end == -1:
            break

        if start > 0:
            parts.append({"type": "text", "content": remaining[:start]})

        emote_str = remaining[start + 1:end]
        emote_parts = emote_str.split(':')
        if len(emote_parts) == 3:
            emote_id = emote_parts[1]
            emote_name = emote_parts[2]

            if emote_id in added_emotes:
                emote_uuid = added_emotes[emote_id]["uuid"]
            else:
                emote_data = download_emote(emote_id)
                if emote_data:
                    emote_uuid = str(uuid.uuid4())
                    added_emotes[emote_id] = {
                        "id": emote_id,
                        "name": emote_name,
                        "uuid": emote_uuid
                    }
                else:
                    remaining = remaining[end + 1:]
                    continue

            emoticons.append({
                "_id": emote_uuid,
                "begin": start,
                "end": end
            })

            parts.append({
                "type": "emote",
                "content": emote_name,
                "id": emote_uuid
            })

        remaining = remaining[end + 1:]

    if remaining:
        parts.append({"type": "text", "content": remaining})

    for part in parts:
        if part["type"] == "text":
            fragments.append({"text": part["content"], "emoticon": None})
        else:
            fragments.append({
                "text": part["content"],
                "emoticon": None
            })

    return {
        "fragments": fragments,
        "emoticons": []
    }


def convert_kick_to_twitch(
    kick_messages, input_file, cache_folder=None, no_save_cache=False,
    ffmpeg_path='ffmpeg', max_size=None
):
    if not kick_messages:
        print("Error: No messages to convert")
        return None

    try:
        first_msg_time = datetime.strptime(
            kick_messages[0]["createdAt"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        last_msg_time = datetime.strptime(
            kick_messages[-1]["createdAt"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        duration_seconds = int((last_msg_time - first_msg_time).total_seconds())
        duration_seconds = max(1, duration_seconds)
    except ValueError:
        print("Error: Invalid date format in messages")
        return None

    twitch_data = {
        "FileInfo": {
            "Version": {"Major": 1, "Minor": 4, "Patch": 0},
            "CreatedAt": datetime.now(timezone.utc).isoformat(),
            "UpdatedAt": "0001-01-01T00:00:00"
        },
        "streamer": {
            "name": "ConvertedStreamer",
            "login": "convertedstreamer",
            "id": 12345678
        },
        "clipper": None,
        "video": {
            "title": f"Converted from {os.path.basename(input_file)}",
            "description": None,
            "id": str(uuid.uuid4().int)[:10],
            "created_at": first_msg_time.isoformat(),
            "start": 0,
            "end": duration_seconds,
            "length": duration_seconds,
            "viewCount": 100,
            "game": "Just Chatting",
            "chapters": [{
                "id": "",
                "startMilliseconds": 0,
                "lengthMilliseconds": duration_seconds * 1000,
                "type": "GAME_CHANGE",
                "description": "Just Chatting",
                "subDescription": "",
                "thumbnailUrl": None,
                "gameId": "509658",
                "gameDisplayName": "Just Chatting",
            }]
        },
        "comments": [],
        "embeddedData": {
            "thirdParty": [],
            "twitchBadges": [],
            "twitchBits": []
        }
    }

    unique_emotes = {}

    for kick_msg in kick_messages:
        if not isinstance(kick_msg, dict) or "content" not in kick_msg:
            continue

        remaining = kick_msg["content"]
        while True:
            start = remaining.find('[emote:')
            if start == -1:
                break
            end = remaining.find(']', start)
            if end == -1:
                break

            emote_str = remaining[start + 1:end]
            emote_parts = emote_str.split(':')
            if len(emote_parts) == 3:
                emote_id = emote_parts[1]
                emote_name = emote_parts[2]

                if emote_id not in unique_emotes:
                    unique_emotes[emote_id] = {
                        "name": emote_name,
                        "data": None
                    }

                emote_uuid = str(uuid.uuid4())
                added_emotes[emote_id] = {
                    "id": emote_id,
                    "name": emote_name,
                    "uuid": emote_uuid
                }

            remaining = remaining[end + 1:]

    print(f"Found {len(unique_emotes)} unique emotes to download")

    for emote_id, emote_info in unique_emotes.items():
        emote_data = download_emote(
            emote_id, cache_folder, no_save_cache, ffmpeg_path, max_size
        )
        if emote_data:
            emote_uuid = added_emotes[emote_id]["uuid"]
            twitch_data["embeddedData"]["thirdParty"].append({
                "id": emote_uuid,
                "imageScale": 2,
                "data": emote_data["data"],
                "name": emote_info["name"],
                "width": emote_data["width"],
                "height": emote_data["height"],
                "isZeroWidth": False
            })

    for idx, kick_msg in enumerate(kick_messages):
        if not isinstance(kick_msg, dict):
            continue

        try:
            current_time = datetime.strptime(
                kick_msg["createdAt"], "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
        except (ValueError, KeyError):
            continue

        time_diff = (current_time - first_msg_time).total_seconds()
        parsed = parse_kick_message(kick_msg.get("content", ""))
        commenter_id = str(kick_msg.get("userId", uuid.uuid4().int & (1 << 32) - 1))

        twitch_data["comments"].append({
            "_id": str(uuid.uuid4()),
            "created_at": current_time.isoformat(),
            "channel_id": "12345678",
            "content_type": "video",
            "content_id": twitch_data["video"]["id"],
            "content_offset_seconds": int(time_diff),
            "commenter": {
                "display_name": kick_msg.get("username", "unknown"),
                "_id": commenter_id,
                "name": kick_msg.get("username", "unknown").lower(),
                "bio": f"User converted from Kick ({os.path.basename(input_file)})",
                "created_at": "2020-01-01T00:00:00Z",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            "message": {
                "body": kick_msg.get("content", ""),
                "bits_spent": 0,
                "fragments": parsed["fragments"],
                "user_badges": [],
                "user_color": "#" + ''.join([
                    format((uuid.uuid4().fields[0] >> i * 8) & 0xff, '02x') for i in range(3)
                ]),
                "emoticons": parsed["emoticons"]
            }
        })

        if (idx + 1) % 1000 == 0:
            print(f"Processed {idx + 1}/{len(kick_messages)} messages")

    print(f"Conversion complete. Total emotes: {len(added_emotes)}")
    return twitch_data


def convert_kick_chat_file(
    input_path, output_path, cache_folder=None, no_save_cache=False,
    ffmpeg_path='ffmpeg', max_size=None
):
    """Function to convert Kick chat messages file to Twitch format and save result."""
    print(f"Reading input file: {input_path}")
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            kick_messages = json.load(f)
        if not isinstance(kick_messages, list):
            raise ValueError("Input JSON should be an array of messages")
    except Exception as e:
        print(f"Error reading file: {e}")
        return None

    if cache_folder:
        print(f"Loading emote cache from: {cache_folder}")
        load_cache_from_folder(cache_folder)

    print(f"Found {len(kick_messages)} messages to convert")
    print("Starting conversion...")

    twitch_data = convert_kick_to_twitch(
        kick_messages,
        input_path,
        cache_folder=cache_folder,
        no_save_cache=no_save_cache,
        ffmpeg_path=ffmpeg_path,
        max_size=max_size
    )

    if twitch_data:
        print(f"Saving result to: {output_path}")
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(twitch_data, f, ensure_ascii=False, indent=2)
            print("Conversion completed successfully!")
            print(f"Stats: {len(twitch_data['comments'])} messages, "
                  f"{len(twitch_data['embeddedData']['thirdParty'])} unique emotes")
            return twitch_data
        except Exception as e:
            print(f"Error saving file: {e}")
            return None

    return None


def main():
    parser = argparse.ArgumentParser(description='Convert Kick chat messages to Twitch format')
    parser.add_argument('input', help='Input Kick JSON file')
    parser.add_argument('output', help='Output Twitch JSON file')
    parser.add_argument('--cache-folder', help='Folder to cache downloaded emotes', default=None)
    parser.add_argument('--no-save-cache', help='Disable saving emotes to cache folder', action='store_true')
    parser.add_argument('--ffmpeg-path', help='Custom path to ffmpeg executable', default='ffmpeg')
    parser.add_argument('--max-size', type=int, help='Max size (width/height) for emotes in pixels', default=None)

    args = parser.parse_args()

    convert_kick_chat_file(
        args.input,
        args.output,
        cache_folder=args.cache_folder,
        no_save_cache=args.no_save_cache,
        ffmpeg_path=args.ffmpeg_path,
        max_size=args.max_size
    )


if __name__ == "__main__":
    main()

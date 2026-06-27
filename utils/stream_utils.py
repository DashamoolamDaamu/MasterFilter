# utils/stream_utils.py
# Adapted from FileToLink (Thunder/utils/bot_utils.py + Thunder/utils/file_properties.py)
# Generates stream and download URLs from a BIN_CHANNEL message.

import logging
import re
from datetime import datetime as dt
from typing import Any, Dict, Optional
from urllib.parse import quote

from pyrogram.types import Message

logger = logging.getLogger(__name__)

# ─── File property helpers (from FileToLink/file_properties.py) ───────────────

def _get_stream_media(message: Message) -> Optional[Any]:
    """Return the media object from a message (same priority order as FileToLink)."""
    for attr in ("video", "document", "audio", "animation", "voice",
                 "video_note", "photo", "sticker"):
        media = getattr(message, attr, None)
        if media:
            return media
    return None


def _get_stream_hash(message: Message) -> str:
    """Return the 6-char secure hash from the message's file_unique_id."""
    media = _get_stream_media(message)
    uniq = getattr(media, "file_unique_id", None) if media else None
    return uniq[:6] if uniq else ""


def _get_stream_fname(message: Message) -> str:
    """Return the filename for a media message, generating one if absent."""
    media = _get_stream_media(message)
    fname = getattr(media, "file_name", None) if media else None
    if fname:
        return fname

    ext = "bin"
    if media:
        ext_map = {
            "photo": "jpg",
            "audio": "mp3",
            "voice": "ogg",
            "video": "mp4",
            "animation": "mp4",
            "video_note": "mp4",
            "sticker": "webp",
        }
        for attr, extension in ext_map.items():
            if getattr(message, attr, None) is not None:
                ext = extension
                break
    ts = dt.now().strftime("%Y%m%d%H%M%S")
    return f"StreamFile_{ts}.{ext}"


def _get_stream_fsize(message: Message) -> int:
    media = _get_stream_media(message)
    return int(getattr(media, "file_size", 0) or 0) if media else 0


def _quote_media_name(file_name: str) -> str:
    return quote(str(file_name).replace("/", "_"), safe="")


# ─── URL generation (from FileToLink/bot_utils.py) ────────────────────────────

def gen_stream_links(bin_msg: Message, base_url: str) -> Dict[str, str]:
    """
    Given a message that was forwarded to BIN_CHANNEL, return:
        {
          "stream_link":  full URL to the Vidstack web player,
          "online_link":  direct stream/download URL,
          "file_name":    raw filename,
        }
    URL scheme mirrors FileToLink exactly:
        stream  → {BASE_URL}/watch/{hash}{msg_id}/{encoded_name}
        download → {BASE_URL}/{hash}{msg_id}/{encoded_name}
    """
    base_url = base_url.rstrip("/")
    secure_hash = _get_stream_hash(bin_msg)
    msg_id = bin_msg.id
    file_name = _get_stream_fname(bin_msg)
    encoded_name = _quote_media_name(file_name)

    stream_link = f"{base_url}/watch/{secure_hash}{msg_id}/{encoded_name}"
    online_link = f"{base_url}/{secure_hash}{msg_id}/{encoded_name}"

    return {
        "stream_link": stream_link,
        "online_link": online_link,
        "file_name": file_name,
    }

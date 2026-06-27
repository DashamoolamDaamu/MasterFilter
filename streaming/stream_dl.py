# utils/stream_dl.py
# Adapted from FileToLink (Thunder/utils/custom_dl.py)
# Streams Telegram media from BIN_CHANNEL in byte chunks for HTTP responses.

import asyncio
import logging
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, Optional

from pyrogram import Client
from pyrogram.errors import FloodWait
from pyrogram.types import Message

logger = logging.getLogger(__name__)


class _FileNotFound(Exception):
    pass


class _InvalidHash(Exception):
    pass


def _get_stream_media(message: Message) -> Optional[Any]:
    for attr in ("video", "document", "audio", "animation", "voice",
                 "video_note", "photo", "sticker"):
        media = getattr(message, attr, None)
        if media:
            return media
    return None


class ByteStreamer:
    """
    Fetches messages from BIN_CHANNEL by message ID and streams them in chunks.
    Direct port of FileToLink's ByteStreamer — only dependency change is using
    the filter-bot's own Client instead of FileToLink's StreamBot.
    """

    __slots__ = ("client", "chat_id")

    def __init__(self, client: Client, bin_channel: int) -> None:
        self.client = client
        self.chat_id = int(bin_channel)

    # ── Internal message fetch ──────────────────────────────────────────────

    async def get_message(self, message_id: int) -> Message:
        while True:
            try:
                msg = await self.client.get_messages(self.chat_id, message_id)
                break
            except FloodWait as e:
                logger.debug(f"FloodWait: get_message, sleeping {e.value}s")
                await asyncio.sleep(e.value)
            except Exception as e:
                logger.debug(f"Error fetching message {message_id}: {e}")
                raise _FileNotFound(f"Message {message_id} not found") from e

        if not msg or not msg.media:
            raise _FileNotFound(f"Message {message_id} has no media")
        return msg

    # ── File info ───────────────────────────────────────────────────────────

    def get_file_info_sync(self, message: Message) -> Dict[str, Any]:
        media = _get_stream_media(message)
        if not media:
            return {"message_id": message.id, "error": "No media"}

        media_type = type(media).__name__.lower()
        file_name = getattr(media, "file_name", None)
        mime_type = getattr(media, "mime_type", None)

        if not file_name:
            ext_map = {
                "photo": "jpg", "audio": "mp3", "voice": "ogg",
                "video": "mp4", "animation": "mp4",
                "videonote": "mp4", "sticker": "webp",
            }
            ext = ext_map.get(media_type, "bin")
            file_name = f"file_{message.id}.{ext}"

        if not mime_type:
            mime_map = {
                "photo": "image/jpeg",
                "voice": "audio/ogg",
                "videonote": "video/mp4",
            }
            mime_type = mime_map.get(media_type, "application/octet-stream")

        return {
            "message_id": message.id,
            "file_size": int(getattr(media, "file_size", 0) or 0),
            "file_name": file_name,
            "mime_type": mime_type,
            "unique_id": getattr(media, "file_unique_id", None),
            "media_type": media_type,
        }

    async def get_file_info(self, message_id: int) -> Dict[str, Any]:
        try:
            msg = await self.get_message(message_id)
            return self.get_file_info_sync(msg)
        except Exception as e:
            logger.debug(f"Error getting file info for {message_id}: {e}")
            return {"message_id": message_id, "error": str(e)}

    # ── Streaming ───────────────────────────────────────────────────────────

    async def stream_file(
        self,
        media_ref: "int | Message",
        offset: int = 0,
        limit: int = 0,
        fallback_message_id: Optional[int] = None,
        on_fallback_message: Optional[Callable[[Message], Awaitable[None]]] = None,
    ) -> AsyncGenerator[bytes, None]:
        chunk_offset = offset // (1024 * 1024)
        chunk_limit = 0
        if limit > 0:
            chunk_limit = ((limit + (1024 * 1024) - 1) // (1024 * 1024)) + 1

        refs = [media_ref]
        media_id = media_ref if isinstance(media_ref, int) else None
        if isinstance(media_ref, Message):
            media_id = getattr(media_ref, "id", getattr(media_ref, "message_id", None))
        if fallback_message_id is not None and (
            media_id is None or fallback_message_id != media_id
        ):
            refs.append(fallback_message_id)

        last_error: Optional[Exception] = None
        for ref in refs:
            started_stream = False
            while True:
                try:
                    target = await self.get_message(ref) if isinstance(ref, int) else ref
                    if (
                        on_fallback_message is not None
                        and fallback_message_id is not None
                        and ref == fallback_message_id
                        and isinstance(target, Message)
                    ):
                        await on_fallback_message(target)
                    async for chunk in self.client.stream_media(
                        target, offset=chunk_offset, limit=chunk_limit
                    ):
                        started_stream = True
                        yield chunk
                    return
                except FloodWait as e:
                    logger.debug(f"FloodWait: stream_file, sleeping {e.value}s")
                    await asyncio.sleep(e.value)
                except _FileNotFound:
                    last_error = _FileNotFound(f"Ref {ref} not found")
                    break
                except Exception as e:
                    if started_stream:
                        raise
                    last_error = e
                    break

        if last_error is not None:
            raise last_error

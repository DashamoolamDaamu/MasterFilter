# utils/stream_render.py
# Adapted from FileToLink (Thunder/utils/render_template.py)
# Renders the web-player (req.html) and download-redirect (dl.html) pages.

import logging
import urllib.parse

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

_template_env = Environment(
    loader=FileSystemLoader("template"),
    autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=True),
    enable_async=True,
    cache_size=200,
    auto_reload=False,
    optimized=True,
)


async def render_stream_page(file_name: str, src: str) -> str:
    """Render the Vidstack web player page (req.html)."""
    template = _template_env.get_template("req.html")
    context = {
        "heading": f"View {file_name}",
        "file_name": file_name,
        "src": f"{src}?disposition=inline",
    }
    return await template.render_async(**context)


async def render_download_page(file_name: str, src: str) -> str:
    """Render the download-redirect page (dl.html)."""
    template = _template_env.get_template("dl.html")
    context = {"file_name": file_name, "src": src}
    return await template.render_async(**context)


async def render_stream_page_for_message(
    message_id: int,
    secure_hash: str,
    base_url: str,
    file_name: str,
    file_unique_id: str,
) -> str:
    """
    Build the stream player page for a known BIN_CHANNEL message.
    Validates that the secure_hash (first 6 chars of file_unique_id) matches.
    """
    if not file_unique_id or file_unique_id[:6] != secure_hash:
        raise ValueError("Hash mismatch")

    encoded_name = urllib.parse.quote(file_name.replace("/", "_"), safe="")
    src = f"{base_url.rstrip('/')}/{secure_hash}{message_id}/{encoded_name}"
    return await render_stream_page(file_name, src)

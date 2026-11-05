"""Thin client for the bits of Majestic's HTTP/RTSP surface the camera uses."""

from __future__ import annotations

from urllib.parse import quote, urlsplit

import aiohttp

from .const import RTSP_PATH, RTSP_PORT, SNAPSHOT_PATH

SNAPSHOT_TIMEOUT = aiohttp.ClientTimeout(total=10)


class MajesticError(Exception):
    """Majestic could not be reached or returned something unusable."""


class MajesticAuthError(MajesticError):
    """Majestic rejected the credentials."""


def host_from_url(value: str) -> str | None:
    """Host in a URL such as catd's rtsp://<ip>:554/stream=0, or a bare host."""
    if "://" in value:
        return urlsplit(value).hostname
    return value.strip() or None


def rtsp_url(host: str, username: str, password: str) -> str:
    """Main-stream RTSP URL with credentials escaped for URL parsing."""
    user = quote(username, safe="")
    secret = quote(password, safe="")
    return f"rtsp://{user}:{secret}@{host}:{RTSP_PORT}/{RTSP_PATH}"


async def async_fetch_snapshot(
    session: aiohttp.ClientSession, host: str, username: str, password: str
) -> bytes:
    """Return a JPEG still from Majestic."""
    try:
        async with session.get(
            f"http://{host}{SNAPSHOT_PATH}",
            headers={"Authorization": aiohttp.encode_basic_auth(username, password)},
            timeout=SNAPSHOT_TIMEOUT,
        ) as resp:
            if resp.status == 401:
                raise MajesticAuthError
            if resp.status != 200:
                raise MajesticError(f"HTTP {resp.status}")
            return await resp.read()
    except (TimeoutError, aiohttp.ClientError) as err:
        raise MajesticError(str(err)) from err

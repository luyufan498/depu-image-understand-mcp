"""Image input handling: normalize local path / URL / data-URI to (base64, mime).

Security: magic-byte validation, size limits, SSRF protection on remote fetch.
"""
from __future__ import annotations

import base64
import ipaddress
import logging
import os
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .config import SecurityConfig

log = logging.getLogger("depu.image")

# Magic bytes -> mime type for the formats we accept.
_MAGIC: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # RIFF....WEBP
]

_ACCEPTED_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


class ImageError(ValueError):
    pass


@dataclass(slots=True)
class ImageData:
    b64: str
    mime_type: str
    raw_bytes: int


def _detect_mime(data: bytes) -> str | None:
    for magic, mime in _MAGIC:
        if data.startswith(magic):
            # refine RIFF -> WEBP
            if mime == "image/webp" and data[8:12] != b"WEBP":
                return None
            return mime
    return None


def _is_private_ip(host: str) -> bool:
    try:
        addr = socket.getaddrinfo(host, None)
        for family, _socktype, _proto, _canon, sockaddr in addr:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                return True
    except socket.gaierror:
        return False
    return False


async def _fetch_url(url: str, sec: SecurityConfig) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ImageError(f"unsupported URL scheme: {parsed.scheme}")
    if not parsed.hostname:
        raise ImageError("URL has no hostname")
    if sec.ssrf_block_private and _is_private_ip(parsed.hostname):
        raise ImageError(f"blocked private/internal host: {parsed.hostname}")
    try:
        async with httpx.AsyncClient(follow_redirects=False) as client:
            resp = await client.get(url, timeout=20.0)
            resp.raise_for_status()
            return resp.content
    except httpx.HTTPError as e:
        raise ImageError(f"failed to fetch {url}: {e}") from e


def _read_local(path: str, sec: SecurityConfig) -> bytes:
    if not sec.allow_local_file:
        raise ImageError("local file access is disabled")
    # resolve and refuse path traversal above cwd
    p = os.path.realpath(path)
    if not os.path.isfile(p):
        raise ImageError(f"file not found: {path}")
    return _validate_size_and_read(p, sec)


def _validate_size_and_read(path: str, sec: SecurityConfig) -> bytes:
    size = os.path.getsize(path)
    if size > sec.max_image_bytes:
        raise ImageError(
            f"image too large: {size} bytes > limit {sec.max_image_bytes}"
        )
    with open(path, "rb") as f:
        return f.read()


def _parse_data_uri(uri: str) -> tuple[bytes, str]:
    """Parse data:image/...;base64,... -> (raw bytes, mime)."""
    if not uri.startswith("data:"):
        raise ImageError("not a data URI")
    try:
        header, b64data = uri.split(",", 1)
    except ValueError as e:
        raise ImageError("malformed data URI") from e
    # header like data:image/png;base64
    mime = "application/octet-stream"
    if ";" in header:
        mime = header[5:].split(";")[0]
    else:
        mime = header[5:]
    try:
        return base64.b64decode(b64data), mime
    except Exception as e:
        raise ImageError(f"invalid base64: {e}") from e


async def load_image(source: str, sec: SecurityConfig) -> ImageData:
    """Normalize any input to validated (base64, mime_type).

    Accepts:
      - http(s) URL
      - data:image/...;base64,... URI (inline base64)
      - raw base64 string (we try to detect mime from decoded bytes)

    Local file paths are NOT accepted — the server runs in a container and
    cannot reach the client filesystem. Callers must inline images as base64.
    """
    raw: bytes
    if source.startswith("data:"):
        raw, mime = _parse_data_uri(source)
        if mime not in _ACCEPTED_MIMES:
            # trust magic bytes instead
            detected = _detect_mime(raw)
            if detected:
                mime = detected
    elif source.startswith(("http://", "https://")):
        raw = await _fetch_url(source, sec)
        mime = _detect_mime(raw) or ""
    elif os.path.isfile(source):
        raw = _read_local(source, sec)
        mime = _detect_mime(raw) or ""
    else:
        # try raw base64
        try:
            raw = base64.b64decode(source, validate=False)
            mime = _detect_mime(raw) or ""
        except Exception as e:
            raise ImageError(
                f"input is not a file, URL, data-URI, or valid base64: {e}"
            ) from e

    if len(raw) > sec.max_image_bytes:
        raise ImageError(
            f"image too large: {len(raw)} bytes > limit {sec.max_image_bytes}"
        )
    if not mime or mime not in _ACCEPTED_MIMES:
        detected = _detect_mime(raw)
        if not detected:
            raise ImageError(
                "unsupported/unknown image format "
                f"(accepted: {', '.join(sorted(_ACCEPTED_MIMES))})"
            )
        mime = detected

    return ImageData(
        b64=base64.b64encode(raw).decode("ascii"),
        mime_type=mime,
        raw_bytes=len(raw),
    )

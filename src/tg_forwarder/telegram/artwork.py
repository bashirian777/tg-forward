"""Prepare Telegram artwork without decoding video files."""
import io
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageOps
from telethon.tl.types import (
    Message, PhotoCachedSize, PhotoSize, PhotoSizeProgressive, PhotoStrippedSize,
)


@dataclass
class MediaArtwork:
    message: Message
    thumb: Optional[str] = None
    cover: Optional[str] = None

    @property
    def paths(self):
        return [path for path in (self.thumb, self.cover) if path]


def artwork_sizes(sizes, thumbnail=True):
    """Try usable static sizes first, leaving embedded previews as fallback."""
    static = [size for size in sizes or [] if isinstance(
        size, (PhotoSize, PhotoSizeProgressive, PhotoCachedSize)
    )]
    if thumbnail:
        fitting = [size for size in static if max(size.w, size.h) <= 320]
        larger = [size for size in static if max(size.w, size.h) > 320]
        static = sorted(fitting, key=lambda s: s.w * s.h, reverse=True) + sorted(
            larger, key=lambda s: s.w * s.h, reverse=True
        )
    else:
        static.sort(key=lambda s: s.w * s.h, reverse=True)
    return static + [s for s in sizes or [] if isinstance(s, PhotoStrippedSize)]


def normalize_artwork(data: bytes, thumbnail=True) -> bytes:
    """Decode artwork and produce JPEG; thumbnails stay below 20 KB/320 px."""
    with Image.open(io.BytesIO(data)) as source:
        source.load()
        image = ImageOps.exif_transpose(source).convert("RGB")
    image.thumbnail((320, 320) if thumbnail else (1280, 1280), Image.Resampling.LANCZOS)
    while True:
        for quality in (85, 70, 55, 40):
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=quality, optimize=True)
            encoded = output.getvalue()
            if not thumbnail or len(encoded) < 20 * 1024:
                return encoded
        image.thumbnail(
            (max(1, image.width // 2), max(1, image.height // 2)),
            Image.Resampling.LANCZOS,
        )

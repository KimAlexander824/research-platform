"""Определение типа файла по содержимому (B6: проверять тип файла).

Тип определяется по первым байтам файла, а не по расширению или заголовку Content-Type,
которые клиент может подменить.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FileType:
    extension: str
    mime_type: str


JPEG = FileType("jpg", "image/jpeg")
PNG = FileType("png", "image/png")
WEBP = FileType("webp", "image/webp")


def detect_image_type(data: bytes) -> FileType | None:
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP
    return None

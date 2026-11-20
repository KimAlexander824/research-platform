"""Языки платформы (B12): русский, узбекский (латиница), английский."""

from enum import StrEnum


class Language(StrEnum):
    RU = "ru"
    UZ = "uz"
    EN = "en"


DEFAULT_LANGUAGE = Language.RU

"""Приватное файловое хранилище (B6).

Файлы лежат в S3-совместимом хранилище (RustFS локально, любое S3 в production),
в БД — только метаданные и ключ объекта.
Бакет закрыт: прямого публичного доступа к файлам нет. Скачать файл можно только по временной
ссылке, которую бэкенд выдаёт после проверки прав.
"""

import asyncio
import logging
from functools import lru_cache
from typing import Any
from urllib.parse import quote

import anyio
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


class Storage:
    def __init__(
        self,
        *,
        endpoint_url: str | None,
        public_endpoint_url: str | None,
        access_key: str,
        secret_key: str,
        region: str,
        bucket: str,
    ) -> None:
        self.bucket = bucket
        common: dict[str, Any] = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "region_name": region,
            "config": Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        }
        # Клиент для операций сервера с хранилищем
        self._client = boto3.client("s3", endpoint_url=endpoint_url, **common)
        # Клиент только для подписи ссылок: в ссылке должен быть адрес, доступный браузеру
        self._public_client = boto3.client("s3", endpoint_url=public_endpoint_url, **common)

    async def ensure_bucket(self, attempts: int = 10, delay_seconds: float = 2) -> None:
        """Создаёт бакет, если его нет. Хранилище может стартовать позже API — поэтому повторы."""

        def _ensure() -> None:
            try:
                self._client.head_bucket(Bucket=self.bucket)
            except ClientError:
                self._client.create_bucket(Bucket=self.bucket)
                logger.info("Created storage bucket %s", self.bucket)

        for attempt in range(1, attempts + 1):
            try:
                await anyio.to_thread.run_sync(_ensure)
                return
            except Exception:
                if attempt == attempts:
                    raise
                await asyncio.sleep(delay_seconds)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await anyio.to_thread.run_sync(
            lambda: self._client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        )

    async def delete(self, key: str) -> None:
        await anyio.to_thread.run_sync(lambda: self._client.delete_object(Bucket=self.bucket, Key=key))

    async def exists(self, key: str) -> bool:
        def _exists() -> bool:
            try:
                self._client.head_object(Bucket=self.bucket, Key=key)
                return True
            except ClientError:
                return False

        return await anyio.to_thread.run_sync(_exists)

    def presigned_get_url(self, key: str, *, expires_in: int | None = None, download_name: str | None = None) -> str:
        """Временная ссылка на файл. Подпись считается локально, без запроса к хранилищу."""
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if download_name:
            # filename* (RFC 6266) — чтобы корректно работали кириллица и пробелы в имени
            params["ResponseContentDisposition"] = f"attachment; filename*=UTF-8''{quote(download_name)}"
        return self._public_client.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=expires_in or settings.S3_PRESIGNED_URL_TTL_SECONDS
        )


@lru_cache
def get_storage() -> Storage:
    """Одно хранилище на процесс. Зависимость FastAPI; в тестах подменяется."""
    return Storage(
        endpoint_url=settings.S3_ENDPOINT_URL,
        public_endpoint_url=settings.S3_PUBLIC_ENDPOINT_URL,
        access_key=settings.S3_ACCESS_KEY,
        secret_key=settings.S3_SECRET_KEY,
        region=settings.S3_REGION,
        bucket=settings.S3_BUCKET,
    )

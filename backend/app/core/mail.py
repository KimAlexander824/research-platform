"""Отправка писем.

Бизнес-логика работает с интерфейсом `MailSender` и не знает, какой сервис отправляет письма.
- console — письма выводятся в лог (разработка, тесты);
- resend  — отправка через Resend (https://resend.com).

Resend в тестовом режиме (без подтверждённого домена) отправляет письма
только с адреса onboarding@resend.dev и только на email владельца аккаунта Resend.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import MailBackend, settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str


class MailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class ConsoleMailSender:
    async def send(self, message: EmailMessage) -> None:
        logger.info("EMAIL to=%s subject=%r\n%s", message.to, message.subject, message.text)


class ResendMailSender:
    def __init__(self, api_key: str, sender: str) -> None:
        self.api_key = api_key
        self.sender = sender

    async def send(self, message: EmailMessage) -> None:
        payload = {
            "from": self.sender,
            "to": [message.to],
            "subject": message.subject,
            "text": message.text,
            "html": message.html,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    RESEND_API_URL, json=payload, headers={"Authorization": f"Bearer {self.api_key}"}
                )
            response.raise_for_status()
        except httpx.HTTPError:
            # Письмо отправляется в фоне после ответа клиенту — ошибку только логируем
            logger.exception("Failed to send email to %s via Resend", message.to)


def get_mail_sender() -> MailSender:
    """Зависимость FastAPI. В тестах подменяется через app.dependency_overrides."""
    if settings.MAIL_BACKEND == MailBackend.RESEND:
        return ResendMailSender(settings.RESEND_API_KEY, settings.MAIL_FROM)
    return ConsoleMailSender()

"""Тексты писем на трёх языках (B12). Язык берётся из настроек пользователя."""

from html import escape

from app.core.config import settings
from app.core.language import Language
from app.core.mail import EmailMessage

_VERIFY = {
    Language.RU: {
        "subject": "Подтвердите email",
        "greeting": "Здравствуйте, {name}!",
        "body": "Чтобы подтвердить email, перейдите по ссылке:",
        "expires": "Ссылка действительна {hours} ч.",
        "ignore": "Если вы не регистрировались на платформе, просто проигнорируйте это письмо.",
    },
    Language.UZ: {
        "subject": "Emailingizni tasdiqlang",
        "greeting": "Assalomu alaykum, {name}!",
        "body": "Emailingizni tasdiqlash uchun havolaga o'ting:",
        "expires": "Havola {hours} soat davomida amal qiladi.",
        "ignore": "Agar siz platformada ro'yxatdan o'tmagan bo'lsangiz, ushbu xatni e'tiborsiz qoldiring.",
    },
    Language.EN: {
        "subject": "Confirm your email",
        "greeting": "Hello, {name}!",
        "body": "To confirm your email, follow the link:",
        "expires": "The link is valid for {hours} h.",
        "ignore": "If you did not sign up on the platform, just ignore this email.",
    },
}

_RESET = {
    Language.RU: {
        "subject": "Восстановление пароля",
        "greeting": "Здравствуйте, {name}!",
        "body": "Чтобы задать новый пароль, перейдите по ссылке:",
        "expires": "Ссылка действительна {minutes} мин.",
        "ignore": "Если вы не запрашивали восстановление пароля, просто проигнорируйте это письмо.",
    },
    Language.UZ: {
        "subject": "Parolni tiklash",
        "greeting": "Assalomu alaykum, {name}!",
        "body": "Yangi parol o'rnatish uchun havolaga o'ting:",
        "expires": "Havola {minutes} daqiqa davomida amal qiladi.",
        "ignore": "Agar siz parolni tiklashni so'ramagan bo'lsangiz, ushbu xatni e'tiborsiz qoldiring.",
    },
    Language.EN: {
        "subject": "Password reset",
        "greeting": "Hello, {name}!",
        "body": "To set a new password, follow the link:",
        "expires": "The link is valid for {minutes} min.",
        "ignore": "If you did not request a password reset, just ignore this email.",
    },
}


def _link(path: str, token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}{path}?token={token}"


def _build(to: str, texts: dict[str, str], name: str, link: str, expires: str) -> EmailMessage:
    greeting = texts["greeting"].format(name=name)
    text = f"{greeting}\n\n{texts['body']}\n{link}\n\n{expires}\n\n{texts['ignore']}\n"
    html = (
        f"<p>{escape(greeting)}</p>"
        f"<p>{escape(texts['body'])}<br><a href=\"{escape(link)}\">{escape(link)}</a></p>"
        f"<p>{escape(expires)}</p>"
        f"<p style=\"color:#666\">{escape(texts['ignore'])}</p>"
    )
    return EmailMessage(to=to, subject=texts["subject"], text=text, html=html)


def verify_email_message(to: str, name: str, language: Language, token: str) -> EmailMessage:
    texts = _VERIFY[language]
    expires = texts["expires"].format(hours=settings.EMAIL_VERIFICATION_TTL_HOURS)
    return _build(to, texts, name, _link(settings.FRONTEND_VERIFY_EMAIL_PATH, token), expires)


def reset_password_message(to: str, name: str, language: Language, token: str) -> EmailMessage:
    texts = _RESET[language]
    expires = texts["expires"].format(minutes=settings.PASSWORD_RESET_TTL_MINUTES)
    return _build(to, texts, name, _link(settings.FRONTEND_RESET_PASSWORD_PATH, token), expires)

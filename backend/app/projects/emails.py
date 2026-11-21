"""Письмо с приглашением в проект (RU/UZ/EN)."""

from html import escape

from app.core.config import settings
from app.core.language import Language
from app.core.mail import EmailMessage
from app.projects.models import ProjectRole

_ROLE_NAMES = {
    Language.RU: {
        ProjectRole.EDITOR: "участник",
        ProjectRole.VIEWER: "наблюдатель",
        ProjectRole.SUPERVISOR: "руководитель",
        ProjectRole.OWNER: "владелец",
    },
    Language.UZ: {
        ProjectRole.EDITOR: "ishtirokchi",
        ProjectRole.VIEWER: "kuzatuvchi",
        ProjectRole.SUPERVISOR: "ilmiy rahbar",
        ProjectRole.OWNER: "egasi",
    },
    Language.EN: {
        ProjectRole.EDITOR: "member",
        ProjectRole.VIEWER: "viewer",
        ProjectRole.SUPERVISOR: "supervisor",
        ProjectRole.OWNER: "owner",
    },
}

_TEXTS = {
    Language.RU: {
        "subject": "Приглашение в проект «{project}»",
        "body": "{inviter} приглашает вас в проект «{project}» в роли: {role}.",
        "action": "Чтобы принять или отклонить приглашение, войдите на платформу (или зарегистрируйтесь с этим email):",
        "expires": "Приглашение действительно {days} дн.",
    },
    Language.UZ: {
        "subject": "«{project}» loyihasiga taklif",
        "body": "{inviter} sizni «{project}» loyihasiga taklif qilmoqda. Rol: {role}.",
        "action": "Taklifni qabul qilish yoki rad etish uchun platformaga kiring (yoki ushbu email bilan ro'yxatdan o'ting):",
        "expires": "Taklif {days} kun davomida amal qiladi.",
    },
    Language.EN: {
        "subject": "Invitation to the project “{project}”",
        "body": "{inviter} invites you to the project “{project}” as: {role}.",
        "action": "To accept or decline the invitation, sign in to the platform (or sign up with this email):",
        "expires": "The invitation is valid for {days} days.",
    },
}


def invitation_message(
    to: str, language: Language, project_title: str, inviter_name: str, role: ProjectRole
) -> EmailMessage:
    texts = _TEXTS[language]
    role_name = _ROLE_NAMES[language][role]
    link = f"{settings.FRONTEND_URL.rstrip('/')}{settings.FRONTEND_INVITATIONS_PATH}"
    subject = texts["subject"].format(project=project_title)
    body = texts["body"].format(inviter=inviter_name, project=project_title, role=role_name)
    expires = texts["expires"].format(days=settings.INVITATION_TTL_DAYS)
    text = f"{body}\n\n{texts['action']}\n{link}\n\n{expires}\n"
    html = (
        f"<p>{escape(body)}</p>"
        f"<p>{escape(texts['action'])}<br><a href=\"{escape(link)}\">{escape(link)}</a></p>"
        f"<p>{escape(expires)}</p>"
    )
    return EmailMessage(to=to, subject=subject, text=text, html=html)

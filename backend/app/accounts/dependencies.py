"""Зависимости FastAPI для авторизации."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import BackgroundTasks, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.exceptions import AccountDisabledError, InvalidTokenError
from app.accounts.models import User, UserRole
from app.accounts.repository import SessionRepository, UserRepository
from app.accounts.service import AccountEmailService, AuthService, ClientInfo, ProfileService, SendEmail
from app.core.database import get_db
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.mail import EmailMessage, MailSender, get_mail_sender
from app.core.rate_limit import client_ip
from app.core.security import decode_access_token
from app.core.storage import Storage, get_storage

DbSession = Annotated[AsyncSession, Depends(get_db)]

# auto_error=False — чтобы ошибки шли в нашем едином формате
_bearer = HTTPBearer(auto_error=False, description="Access-токен из /auth/login")


@dataclass(frozen=True)
class CurrentUser:
    user: User
    session_id: UUID


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    if credentials is None:
        raise UnauthorizedError()

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise InvalidTokenError()

    try:
        user_id = UUID(payload["sub"])
        session_id = UUID(payload["sid"])
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError() from exc

    # Сессия проверяется на каждом запросе: после выхода или отзыва сессии токен сразу перестаёт работать
    if await SessionRepository(db).get_active(session_id) is None:
        raise InvalidTokenError()

    user = await UserRepository(db).get_by_id(user_id)
    if user is None:
        raise InvalidTokenError()
    if not user.is_active:
        raise AccountDisabledError()

    return CurrentUser(user=user, session_id=session_id)


def require_roles(*roles: UserRole) -> Callable[..., Awaitable[CurrentUser]]:
    """Доступ только для указанных системных ролей:

    @router.get("/...", dependencies=[Depends(require_roles(UserRole.ADMIN))])
    """

    async def dependency(current: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if current.user.role not in roles:
            raise ForbiddenError("Insufficient role")
        return current

    return dependency


def get_send_email(
    background: BackgroundTasks, mail: Annotated[MailSender, Depends(get_mail_sender)]
) -> SendEmail:
    """Письма отправляются в фоне после ответа — клиент не ждёт почтовый сервис."""

    def send(message: EmailMessage) -> None:
        background.add_task(mail.send, message)

    return send


SendEmailDep = Annotated[SendEmail, Depends(get_send_email)]


def get_auth_service(db: DbSession, send_email: SendEmailDep) -> AuthService:
    return AuthService(db, send_email)


def get_account_email_service(db: DbSession, send_email: SendEmailDep) -> AccountEmailService:
    return AccountEmailService(db, send_email)


def get_client_info(request: Request) -> ClientInfo:
    return ClientInfo(ip_address=client_ip(request), user_agent=request.headers.get("user-agent"))


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
def get_profile_service(
    db: DbSession, storage: Annotated[Storage, Depends(get_storage)], send_email: SendEmailDep
) -> ProfileService:
    return ProfileService(db, storage, send_email)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
ProfileServiceDep = Annotated[ProfileService, Depends(get_profile_service)]
AccountEmailServiceDep = Annotated[AccountEmailService, Depends(get_account_email_service)]
ClientInfoDep = Annotated[ClientInfo, Depends(get_client_info)]

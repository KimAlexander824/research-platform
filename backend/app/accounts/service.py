"""Регистрация, вход, обновление токенов и управление сессиями (B2)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.emails import reset_password_message, verify_email_message
from app.accounts.exceptions import (
    AccountDisabledError,
    EmailAlreadyExistsError,
    EmailAlreadyVerifiedError,
    EmailCooldownError,
    InvalidCredentialsError,
    InvalidEmailTokenError,
    InvalidPasswordError,
    InvalidRefreshTokenError,
    SessionNotFoundError,
    TooManyLoginAttemptsError,
)
from app.accounts.models import EmailToken, EmailTokenPurpose, User, UserRole, UserSession
from app.accounts.repository import EmailTokenRepository, SessionRepository, UserRepository
from app.accounts.schemas import ChangeEmailIn, LoginIn, ProfileUpdateIn, RegisterIn, ResetPasswordIn
from app.core.config import settings
from app.core.errors import FileTooLargeError, UnsupportedFileTypeError
from app.core.files import detect_image_type
from app.core.language import DEFAULT_LANGUAGE
from app.core.mail import EmailMessage
from app.core.redis import get_redis
from app.core.storage import Storage
from app.core.security import (
    create_access_token,
    generate_secure_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)


@dataclass(frozen=True)
class ClientInfo:
    ip_address: str | None
    user_agent: str | None


# Постановка письма в очередь на отправку (в роутере — фоновая задача после ответа)
SendEmail = Callable[[EmailMessage], None]


@dataclass(frozen=True)
class AuthTokens:
    access_token: str
    expires_in: int
    refresh_token: str


class LoginAttempts:
    """Счётчик неудачных попыток входа по email (защита от перебора паролей)."""

    @staticmethod
    def _key(email: str) -> str:
        return f"login_fail:{email}"

    async def check(self, email: str) -> None:
        redis = get_redis()
        attempts = await redis.get(self._key(email))
        if attempts is not None and int(attempts) >= settings.LOGIN_MAX_ATTEMPTS:
            ttl = await redis.ttl(self._key(email))
            raise TooManyLoginAttemptsError(headers={"Retry-After": str(max(ttl, 1))})

    async def register_failure(self, email: str) -> None:
        redis = get_redis()
        key = self._key(email)
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, settings.LOGIN_LOCKOUT_MINUTES * 60)

    async def reset(self, email: str) -> None:
        await get_redis().delete(self._key(email))


class AuthService:
    def __init__(self, db: AsyncSession, send_email: SendEmail) -> None:
        self.db = db
        self.users = UserRepository(db)
        self.sessions = SessionRepository(db)
        self.attempts = LoginAttempts()
        self.emails = AccountEmailService(db, send_email)

    async def register(self, data: RegisterIn, client: ClientInfo) -> AuthTokens:
        if await self.users.get_by_email(data.email) is not None:
            raise EmailAlreadyExistsError()

        # По решению заказчика все регистрируются как исследователи;
        # роль руководителя назначает администратор или выдаётся при приглашении
        user = User(
            email=data.email,
            password_hash=hash_password(data.password),
            full_name=data.full_name,
            role=UserRole.RESEARCHER,
            language=data.language or DEFAULT_LANGUAGE,
        )
        self.users.add(user)
        try:
            await self.db.flush()
        except IntegrityError as exc:  # одновременная регистрация с тем же email
            await self.db.rollback()
            raise EmailAlreadyExistsError() from exc

        tokens = self._start_session(user, client)
        await self.emails.send_verification(user)
        await self.db.commit()
        return tokens

    async def login(self, data: LoginIn, client: ClientInfo) -> AuthTokens:
        await self.attempts.check(data.email)

        user = await self.users.get_by_email(data.email)
        if user is None or not verify_password(data.password, user.password_hash):
            await self.attempts.register_failure(data.email)
            raise InvalidCredentialsError()
        if not user.is_active:
            raise AccountDisabledError()

        await self.attempts.reset(data.email)
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(data.password)

        tokens = self._start_session(user, client)
        await self.db.commit()
        return tokens

    async def refresh(self, refresh_token: str | None, client: ClientInfo) -> AuthTokens:
        """Выдаёт новую пару токенов. Старый refresh-токен после этого недействителен."""
        if not refresh_token:
            raise InvalidRefreshTokenError()

        session = await self.sessions.get_by_token_hash(hash_token(refresh_token))
        now = datetime.now(UTC)
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            raise InvalidRefreshTokenError()

        user = await self.users.get_by_id(session.user_id)
        if user is None or not user.is_active:
            session.revoked_at = now
            await self.db.commit()
            raise InvalidRefreshTokenError()

        new_refresh = generate_secure_token()
        session.refresh_token_hash = hash_token(new_refresh)
        session.last_used_at = now
        session.ip_address = client.ip_address
        session.user_agent = (client.user_agent or "")[:512] or None
        await self.db.commit()

        access_token, expires_in = create_access_token(user.id, session.id)
        return AuthTokens(access_token, expires_in, new_refresh)

    async def logout(self, session_id: UUID) -> None:
        session = await self.sessions.get_active(session_id)
        if session is not None:
            session.revoked_at = datetime.now(UTC)
            await self.db.commit()

    async def list_sessions(self, user_id: UUID) -> list[UserSession]:
        return await self.sessions.list_active_for_user(user_id)

    async def revoke_session(self, user_id: UUID, session_id: UUID) -> None:
        session = await self.sessions.get_active(session_id)
        # Чужую сессию не раскрываем: для пользователя её «не существует»
        if session is None or session.user_id != user_id:
            raise SessionNotFoundError()
        session.revoked_at = datetime.now(UTC)
        await self.db.commit()

    async def revoke_other_sessions(self, user_id: UUID, current_session_id: UUID) -> None:
        await self.sessions.revoke_all_for_user(user_id, except_session_id=current_session_id)
        await self.db.commit()

    def _start_session(self, user: User, client: ClientInfo) -> AuthTokens:
        refresh_token = generate_secure_token()
        session = UserSession(
            id=uuid4(),
            user_id=user.id,
            refresh_token_hash=hash_token(refresh_token),
            ip_address=client.ip_address,
            user_agent=(client.user_agent or "")[:512] or None,
            expires_at=datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS),
        )
        self.sessions.add(session)
        access_token, expires_in = create_access_token(user.id, session.id)
        return AuthTokens(access_token, expires_in, refresh_token)


class EmailCooldown:
    """Не чаще одного письма одного типа на адрес за EMAIL_RESEND_COOLDOWN_SECONDS."""

    @staticmethod
    def _key(purpose: EmailTokenPurpose, email: str) -> str:
        return f"email_cooldown:{purpose.value}:{email}"

    async def acquire(self, purpose: EmailTokenPurpose, email: str) -> int | None:
        """Возвращает None, если можно отправлять, иначе — сколько секунд ждать."""
        redis = get_redis()
        key = self._key(purpose, email)
        if await redis.set(key, "1", ex=settings.EMAIL_RESEND_COOLDOWN_SECONDS, nx=True):
            return None
        return max(await redis.ttl(key), 1)


class AccountEmailService:
    """Подтверждение email и восстановление пароля (B2)."""

    def __init__(self, db: AsyncSession, send_email: SendEmail) -> None:
        self.db = db
        self.send_email = send_email
        self.users = UserRepository(db)
        self.sessions = SessionRepository(db)
        self.tokens = EmailTokenRepository(db)
        self.cooldown = EmailCooldown()

    async def send_verification(self, user: User) -> None:
        token = await self._issue(user, EmailTokenPurpose.VERIFY_EMAIL, timedelta(hours=settings.EMAIL_VERIFICATION_TTL_HOURS))
        self.send_email(verify_email_message(user.email, user.full_name, user.language, token))

    async def resend_verification(self, user: User) -> None:
        if user.email_verified:
            raise EmailAlreadyVerifiedError()
        wait = await self.cooldown.acquire(EmailTokenPurpose.VERIFY_EMAIL, user.email)
        if wait is not None:
            raise EmailCooldownError(headers={"Retry-After": str(wait)})
        await self.send_verification(user)
        await self.db.commit()

    async def confirm_email(self, raw_token: str) -> None:
        token = await self.tokens.get_valid(hash_token(raw_token), EmailTokenPurpose.VERIFY_EMAIL)
        if token is None:
            raise InvalidEmailTokenError()
        user = await self.users.get_by_id(token.user_id)
        if user is None:
            raise InvalidEmailTokenError()
        now = datetime.now(UTC)
        token.used_at = now
        if user.email_verified_at is None:
            user.email_verified_at = now
        await self.db.commit()

    async def request_password_reset(self, email: str) -> None:
        """Ответ всегда одинаковый, чтобы нельзя было узнать, зарегистрирован ли email."""
        if await self.cooldown.acquire(EmailTokenPurpose.RESET_PASSWORD, email) is not None:
            return
        user = await self.users.get_by_email(email)
        if user is None or not user.is_active:
            return
        token = await self._issue(user, EmailTokenPurpose.RESET_PASSWORD, timedelta(minutes=settings.PASSWORD_RESET_TTL_MINUTES))
        self.send_email(reset_password_message(user.email, user.full_name, user.language, token))
        await self.db.commit()

    async def reset_password(self, data: ResetPasswordIn) -> None:
        token = await self.tokens.get_valid(hash_token(data.token), EmailTokenPurpose.RESET_PASSWORD)
        if token is None:
            raise InvalidEmailTokenError()
        user = await self.users.get_by_id(token.user_id)
        if user is None or not user.is_active:
            raise InvalidEmailTokenError()

        now = datetime.now(UTC)
        token.used_at = now
        user.password_hash = hash_password(data.new_password)
        # Переход по ссылке из письма подтверждает владение email
        if user.email_verified_at is None:
            user.email_verified_at = now
        # После смены пароля все устройства выходят из аккаунта
        await self.sessions.revoke_all_for_user(user.id)
        await self.db.commit()
        await LoginAttempts().reset(user.email)

    async def _issue(self, user: User, purpose: EmailTokenPurpose, ttl: timedelta) -> str:
        await self.tokens.invalidate_all(user.id, purpose)
        raw = generate_secure_token()
        self.tokens.add(
            EmailToken(
                user_id=user.id,
                purpose=purpose,
                token_hash=hash_token(raw),
                expires_at=datetime.now(UTC) + ttl,
            )
        )
        return raw


# Поля API -> поля модели (settings в API хранится как preferences)
_PROFILE_FIELDS = {
    "full_name": "full_name",
    "phone": "phone",
    "language": "language",
    "organization": "organization",
    "position": "position",
    "academic_degree": "academic_degree",
    "academic_title": "academic_title",
    "research_interests": "research_interests",
    "settings": "preferences",
}


class ProfileService:
    """Профиль пользователя (B2): данные, научная информация, язык, настройки, фото, смена email."""

    def __init__(self, db: AsyncSession, storage: Storage, send_email: SendEmail) -> None:
        self.db = db
        self.storage = storage
        self.users = UserRepository(db)
        self.emails = AccountEmailService(db, send_email)

    def avatar_url(self, user: User) -> str | None:
        return self.storage.presigned_get_url(user.avatar_key) if user.avatar_key else None

    async def update(self, user: User, data: ProfileUpdateIn) -> User:
        for api_field, value in data.model_dump(exclude_unset=True).items():
            setattr(user, _PROFILE_FIELDS[api_field], value)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def change_email(self, user: User, data: ChangeEmailIn) -> User:
        # Пароль защищает от захвата аккаунта, если access-токен попал к постороннему
        if not verify_password(data.current_password, user.password_hash):
            raise InvalidPasswordError()
        if data.new_email == user.email:
            return user
        if await self.users.get_by_email(data.new_email) is not None:
            raise EmailAlreadyExistsError(field="newEmail")

        user.email = data.new_email
        user.email_verified_at = None
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise EmailAlreadyExistsError(field="newEmail") from exc
        await self.emails.send_verification(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def upload_avatar(self, user: User, data: bytes) -> User:
        if len(data) > settings.AVATAR_MAX_SIZE_MB * 1024 * 1024:
            raise FileTooLargeError(f"Max size is {settings.AVATAR_MAX_SIZE_MB} MB")
        file_type = detect_image_type(data)
        if file_type is None:
            raise UnsupportedFileTypeError("Allowed formats: JPEG, PNG, WEBP")

        key = f"avatars/{user.id}/{uuid4()}.{file_type.extension}"
        await self.storage.put(key, data, file_type.mime_type)

        old_key = user.avatar_key
        user.avatar_key = key
        await self.db.commit()
        await self.db.refresh(user)
        if old_key:
            await self.storage.delete(old_key)
        return user

    async def delete_avatar(self, user: User) -> User:
        old_key = user.avatar_key
        if old_key:
            user.avatar_key = None
            await self.db.commit()
            await self.db.refresh(user)
            await self.storage.delete(old_key)
        return user

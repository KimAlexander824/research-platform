"""Запросы к БД для пользователей и сессий."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import EmailToken, EmailTokenPurpose, User, UserSession


class UserRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self.db.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        return await self.db.scalar(select(User).where(User.email == email))

    def add(self, user: User) -> None:
        self.db.add(user)


class SessionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def add(self, session: UserSession) -> None:
        self.db.add(session)

    async def get_active(self, session_id: UUID) -> UserSession | None:
        return await self.db.scalar(
            select(UserSession).where(
                UserSession.id == session_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > datetime.now(UTC),
            )
        )

    async def get_by_token_hash(self, token_hash: str) -> UserSession | None:
        return await self.db.scalar(
            select(UserSession).where(UserSession.refresh_token_hash == token_hash).with_for_update()
        )

    async def list_active_for_user(self, user_id: UUID) -> list[UserSession]:
        result = await self.db.scalars(
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > datetime.now(UTC),
            )
            .order_by(UserSession.last_used_at.desc())
        )
        return list(result.all())

    async def revoke_all_for_user(self, user_id: UUID, except_session_id: UUID | None = None) -> None:
        query = update(UserSession).where(
            UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
        )
        if except_session_id is not None:
            query = query.where(UserSession.id != except_session_id)
        await self.db.execute(query.values(revoked_at=datetime.now(UTC)))


class EmailTokenRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def add(self, token: EmailToken) -> None:
        self.db.add(token)

    async def get_valid(self, token_hash: str, purpose: EmailTokenPurpose) -> EmailToken | None:
        return await self.db.scalar(
            select(EmailToken)
            .where(
                EmailToken.token_hash == token_hash,
                EmailToken.purpose == purpose,
                EmailToken.used_at.is_(None),
                EmailToken.expires_at > datetime.now(UTC),
            )
            .with_for_update()
        )

    async def invalidate_all(self, user_id: UUID, purpose: EmailTokenPurpose) -> None:
        """Делает недействительными все прежние ссылки: работает только последняя."""
        await self.db.execute(
            update(EmailToken)
            .where(EmailToken.user_id == user_id, EmailToken.purpose == purpose, EmailToken.used_at.is_(None))
            .values(used_at=datetime.now(UTC))
        )

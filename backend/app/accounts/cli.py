"""Консольные команды для управления пользователями.

Первый администратор создаётся из консоли (через API стать админом нельзя):

    python -m app.accounts.cli create-admin --email admin@example.com --password "..." --name "Администратор"

Если пользователь с таким email уже есть — ему выдаётся роль admin (пароль не меняется).
В Docker:

    docker compose exec api python -m app.accounts.cli create-admin --email ... --password ... --name ...
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.accounts.models import User, UserRole
from app.accounts.schemas import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from app.audit.service import AuditLogger
from app.core.database import SessionFactory, engine
from app.core.security import hash_password


async def create_admin(email: str, password: str | None, name: str | None) -> str:
    email = email.strip().lower()
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        audit = AuditLogger(db)

        if user is not None:
            if user.role == UserRole.ADMIN:
                return f"{email} уже администратор"
            old_role = user.role
            user.role = UserRole.ADMIN
            audit.log(
                "user.role_changed", entity_type="user", entity_id=user.id,
                data={"role": [old_role, UserRole.ADMIN], "source": "cli"},
            )
            await db.commit()
            return f"{email}: роль изменена на admin"

        if not password or not (PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH):
            raise SystemExit(f"Пароль обязателен, длина {PASSWORD_MIN_LENGTH}–{PASSWORD_MAX_LENGTH} символов")
        user = User(
            email=email,
            password_hash=hash_password(password),
            full_name=(name or "Администратор").strip(),
            role=UserRole.ADMIN,
        )
        db.add(user)
        await db.flush()
        audit.log("user.created_by_cli", entity_type="user", entity_id=user.id, data={"email": email, "role": "admin"})
        await db.commit()
        return f"Создан администратор {email}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.accounts.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-admin", help="Создать администратора или выдать роль admin")
    create.add_argument("--email", required=True)
    create.add_argument("--password", help="Обязателен, если пользователя ещё нет")
    create.add_argument("--name", help="ФИО (по умолчанию «Администратор»)")

    args = parser.parse_args(argv)

    async def run() -> str:
        try:
            return await create_admin(args.email, args.password, args.name)
        finally:
            await engine.dispose()

    print(asyncio.run(run()))
    sys.exit(0)


if __name__ == "__main__":
    main()

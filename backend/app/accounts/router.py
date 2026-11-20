"""Эндпоинты авторизации и текущего пользователя (B2)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, File, Response, UploadFile, status

from app.accounts.dependencies import (
    AccountEmailServiceDep,
    AuthServiceDep,
    ClientInfoDep,
    CurrentUserDep,
    ProfileServiceDep,
)
from app.accounts.models import User
from app.accounts.schemas import (
    ChangeEmailIn,
    EmailTokenIn,
    ForgotPasswordIn,
    LoginIn,
    ProfileUpdateIn,
    RegisterIn,
    ResetPasswordIn,
    SessionOut,
    TokenOut,
    UserOut,
)
from app.accounts.service import AuthTokens
from app.core.config import settings
from app.core.rate_limit import rate_limit

AUTH_COOKIE_PATH = "/api/v1/auth"

auth_limit = Depends(rate_limit("auth", settings.AUTH_RATE_LIMIT_PER_MINUTE))

auth_router = APIRouter(prefix="/auth", tags=["Авторизация"])
me_router = APIRouter(tags=["Текущий пользователь"])

RefreshCookie = Annotated[str | None, Cookie(alias=settings.REFRESH_COOKIE_NAME)]


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=token,
        max_age=settings.REFRESH_TOKEN_TTL_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path=AUTH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.REFRESH_COOKIE_NAME, path=AUTH_COOKIE_PATH)


def _token_response(response: Response, tokens: AuthTokens) -> TokenOut:
    _set_refresh_cookie(response, tokens.refresh_token)
    return TokenOut(access_token=tokens.access_token, expires_in=tokens.expires_in)


@auth_router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    dependencies=[auth_limit],
    summary="Регистрация по email",
    description="Создаёт пользователя с ролью researcher и сразу выполняет вход. "
    "Refresh-токен устанавливается в httpOnly cookie. На email отправляется ссылка для подтверждения.",
)
async def register(data: RegisterIn, response: Response, service: AuthServiceDep, client: ClientInfoDep) -> TokenOut:
    return _token_response(response, await service.register(data, client))


@auth_router.post(
    "/login",
    dependencies=[auth_limit],
    summary="Вход по email и паролю",
    description="После нескольких неудачных попыток вход для этого email временно блокируется (429).",
)
async def login(data: LoginIn, response: Response, service: AuthServiceDep, client: ClientInfoDep) -> TokenOut:
    return _token_response(response, await service.login(data, client))


@auth_router.post(
    "/refresh",
    dependencies=[auth_limit],
    summary="Обновить access-токен",
    description="Берёт refresh-токен из cookie, выдаёт новый access-токен и новый refresh-токен.",
)
async def refresh(
    response: Response,
    service: AuthServiceDep,
    client: ClientInfoDep,
    refresh_token: RefreshCookie = None,
) -> TokenOut:
    return _token_response(response, await service.refresh(refresh_token, client))


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Выход (завершить текущую сессию)")
async def logout(response: Response, current: CurrentUserDep, service: AuthServiceDep) -> None:
    await service.logout(current.session_id)
    _clear_refresh_cookie(response)


@auth_router.get("/sessions", summary="Активные сессии пользователя")
async def list_sessions(current: CurrentUserDep, service: AuthServiceDep) -> list[SessionOut]:
    sessions = await service.list_sessions(current.user.id)
    return [
        SessionOut.model_validate(s).model_copy(update={"is_current": s.id == current.session_id})
        for s in sessions
    ]


@auth_router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Завершить сессию на другом устройстве",
)
async def revoke_session(session_id: UUID, current: CurrentUserDep, service: AuthServiceDep) -> None:
    await service.revoke_session(current.user.id, session_id)


@auth_router.delete(
    "/sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Завершить все сессии, кроме текущей",
)
async def revoke_other_sessions(current: CurrentUserDep, service: AuthServiceDep) -> None:
    await service.revoke_other_sessions(current.user.id, current.session_id)


@auth_router.post(
    "/verify-email/request",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[auth_limit],
    summary="Отправить письмо для подтверждения email повторно",
    description="Предыдущие ссылки перестают действовать. Не чаще раза в минуту.",
)
async def request_email_verification(current: CurrentUserDep, service: AccountEmailServiceDep) -> None:
    await service.resend_verification(current.user)


@auth_router.post(
    "/verify-email/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[auth_limit],
    summary="Подтвердить email по токену из письма",
    description="Не требует входа: ссылку могут открыть на другом устройстве.",
)
async def confirm_email(data: EmailTokenIn, service: AccountEmailServiceDep) -> None:
    await service.confirm_email(data.token)


@auth_router.post(
    "/password/forgot",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[auth_limit],
    summary="Запросить восстановление пароля",
    description="Ответ всегда 202 — независимо от того, зарегистрирован ли email.",
)
async def forgot_password(data: ForgotPasswordIn, service: AccountEmailServiceDep) -> None:
    await service.request_password_reset(data.email)


@auth_router.post(
    "/password/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[auth_limit],
    summary="Задать новый пароль по токену из письма",
    description="После смены пароля все сессии пользователя завершаются.",
)
async def reset_password(data: ResetPasswordIn, service: AccountEmailServiceDep) -> None:
    await service.reset_password(data)


def _user_out(user: User, profile: ProfileServiceDep) -> UserOut:
    return UserOut.model_validate(user).model_copy(update={"avatar_url": profile.avatar_url(user)})


@me_router.get("/me", summary="Профиль текущего пользователя")
async def me(current: CurrentUserDep, profile: ProfileServiceDep) -> UserOut:
    return _user_out(current.user, profile)


@me_router.patch(
    "/me",
    summary="Редактировать профиль",
    description="Передаются только изменяемые поля. `null` очищает необязательное поле "
    "(телефон, научная информация). Email меняется отдельным запросом.",
)
async def update_me(data: ProfileUpdateIn, current: CurrentUserDep, profile: ProfileServiceDep) -> UserOut:
    return _user_out(await profile.update(current.user, data), profile)


@me_router.post(
    "/me/email",
    summary="Сменить email",
    description="Требует текущий пароль. Новый email становится неподтверждённым, "
    "на него отправляется письмо для подтверждения.",
)
async def change_email(data: ChangeEmailIn, current: CurrentUserDep, profile: ProfileServiceDep) -> UserOut:
    return _user_out(await profile.change_email(current.user, data), profile)


@me_router.put(
    "/me/avatar",
    summary="Загрузить фото профиля",
    description="JPEG, PNG или WEBP. Старое фото удаляется.",
)
async def upload_avatar(
    current: CurrentUserDep,
    profile: ProfileServiceDep,
    file: Annotated[UploadFile, File(description="Изображение JPEG, PNG или WEBP")],
) -> UserOut:
    # Читаем на 1 байт больше лимита — этого достаточно, чтобы понять, что файл слишком большой
    data = await file.read(settings.AVATAR_MAX_SIZE_MB * 1024 * 1024 + 1)
    return _user_out(await profile.upload_avatar(current.user, data), profile)


@me_router.delete("/me/avatar", summary="Удалить фото профиля")
async def delete_avatar(current: CurrentUserDep, profile: ProfileServiceDep) -> UserOut:
    return _user_out(await profile.delete_avatar(current.user), profile)

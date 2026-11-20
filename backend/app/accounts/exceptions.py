from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError, UnauthorizedError


class EmailAlreadyExistsError(ConflictError):
    code = "EMAIL_ALREADY_EXISTS"
    message = "User with this email already exists"

    def __init__(self, field: str = "email") -> None:
        super().__init__(fields={field: ["ALREADY_EXISTS"]})


class InvalidCredentialsError(UnauthorizedError):
    code = "INVALID_CREDENTIALS"
    message = "Invalid email or password"


class AccountDisabledError(ForbiddenError):
    code = "ACCOUNT_DISABLED"
    message = "Account is disabled"


class TooManyLoginAttemptsError(AppError):
    status_code = 429
    code = "TOO_MANY_LOGIN_ATTEMPTS"
    message = "Too many failed login attempts, try again later"


class InvalidTokenError(UnauthorizedError):
    code = "INVALID_TOKEN"
    message = "Access token is invalid or expired"


class InvalidRefreshTokenError(UnauthorizedError):
    code = "INVALID_REFRESH_TOKEN"
    message = "Refresh token is invalid or expired"


class SessionNotFoundError(NotFoundError):
    code = "SESSION_NOT_FOUND"
    message = "Session not found"


class InvalidEmailTokenError(AppError):
    status_code = 400
    code = "INVALID_EMAIL_TOKEN"
    message = "Link is invalid, expired or already used"


class EmailAlreadyVerifiedError(ConflictError):
    code = "EMAIL_ALREADY_VERIFIED"
    message = "Email is already verified"


class EmailCooldownError(AppError):
    status_code = 429
    code = "EMAIL_COOLDOWN"
    message = "Email was sent recently, try again later"


class InvalidPasswordError(AppError):
    status_code = 400
    code = "INVALID_PASSWORD"
    message = "Current password is incorrect"

    def __init__(self) -> None:
        super().__init__(fields={"currentPassword": ["INVALID"]})

from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError


class ProjectNotFoundError(NotFoundError):
    code = "PROJECT_NOT_FOUND"
    message = "Project not found"


class MemberNotFoundError(NotFoundError):
    code = "MEMBER_NOT_FOUND"
    message = "Member not found"


class InvitationNotFoundError(NotFoundError):
    code = "INVITATION_NOT_FOUND"
    message = "Invitation not found"


class AlreadyMemberError(ConflictError):
    code = "ALREADY_MEMBER"
    message = "User is already a member of this project"


class InvitationAlreadyPendingError(ConflictError):
    code = "INVITATION_ALREADY_PENDING"
    message = "An active invitation for this email already exists"


class InvitationNotPendingError(ConflictError):
    code = "INVITATION_NOT_PENDING"
    message = "Invitation is no longer active"


class EmailNotVerifiedError(ForbiddenError):
    code = "EMAIL_NOT_VERIFIED"
    message = "Confirm your email to accept invitations"


class OwnerCannotBeChangedError(ConflictError):
    code = "OWNER_CANNOT_BE_CHANGED"
    message = "Project owner cannot be removed or have their role changed"


class ProjectNotArchivedError(AppError):
    status_code = 409
    code = "PROJECT_NOT_ARCHIVED"
    message = "Project is not archived"

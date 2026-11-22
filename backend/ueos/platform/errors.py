class DomainError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail)
        self.detail = detail or self.code


class AuthError(DomainError):
    status = 401
    code = "unauthorized"


class Forbidden(DomainError):
    status = 403
    code = "forbidden"


class NotFound(DomainError):
    status = 404
    code = "not_found"


class Conflict(DomainError):
    status = 409
    code = "conflict"


class Invalid(DomainError):
    status = 422
    code = "invalid"

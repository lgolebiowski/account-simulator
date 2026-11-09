class BankError(Exception):
    """A business-rule violation. The message is safe to show to the user."""
    status_code = 400


class AuthError(BankError):
    status_code = 401


class LockedError(BankError):
    status_code = 403


class NotFoundError(BankError):
    status_code = 404


class ClosedError(BankError):
    status_code = 403

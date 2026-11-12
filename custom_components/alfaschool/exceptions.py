"""Errors without credentials or response bodies."""


class AlfaSchoolError(Exception):
    """Base client error."""


class AuthenticationError(AlfaSchoolError):
    """Credentials were rejected or the session expired."""


class ScheduleError(AlfaSchoolError):
    """The server returned an unexpected schedule."""

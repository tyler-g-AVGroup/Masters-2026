class DemoError(Exception):
    """An actionable connection, device, or demo error."""


class SessionExpired(DemoError):
    """The REST session no longer has a valid login."""

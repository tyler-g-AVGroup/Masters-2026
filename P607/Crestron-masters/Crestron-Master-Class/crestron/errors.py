class DemoError(Exception):
    """An actionable connection, device, or demo error."""


UNTRUSTED_CERTIFICATE = (
    "{} certificate not trusted ({}): a device with a self-signed certificate "
    "needs verify_tls false; otherwise check the device certificate and address."
)


class SessionExpired(DemoError):
    """The REST session no longer has a valid login."""

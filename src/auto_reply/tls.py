"""SSL setup helper.

On corporate Windows machines that MITM TLS via a custom root CA, Python's
default `certifi` bundle does not include the corporate root, so HTTPS to
sites like Railway fails with `CERTIFICATE_VERIFY_FAILED`. `truststore`
makes Python's ssl module use the OS cert store (which curl, browsers, and
admins already trust), so corporate-MITM and standard CAs both work.

Call `enable_system_certs()` once per process, as early as possible — before
any TLS connection is opened. Idempotent.
"""
from __future__ import annotations

_INSTALLED = False


def enable_system_certs() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    import truststore

    truststore.inject_into_ssl()
    _INSTALLED = True

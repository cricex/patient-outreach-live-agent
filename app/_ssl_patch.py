"""TLS 1.3 workaround — MUST be imported before any urllib3/requests usage.

Python 3.12 + OpenSSL 3.x on Windows triggers UNEXPECTED_EOF_WHILE_READING
with TLS 1.3 on certain Azure endpoints when using urllib3/requests.
Patches urllib3 to cap TLS at 1.2.
"""
import ssl
from urllib3.util import ssl_ as _urllib3_ssl
from urllib3 import connection as _urllib3_conn

_orig_create_ctx = _urllib3_ssl.create_urllib3_context


def _patched_create_urllib3_context(*args, **kwargs):
    ctx = _orig_create_ctx(*args, **kwargs)
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    return ctx


# Patch both the definition and the already-imported local reference
_urllib3_ssl.create_urllib3_context = _patched_create_urllib3_context
_urllib3_conn.create_urllib3_context = _patched_create_urllib3_context

"""Voice call FastAPI application package."""
from . import _ssl_patch  # noqa: F401  — must be first to patch TLS before urllib3 is used

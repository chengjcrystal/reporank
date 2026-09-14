"""Shared rate limiter instance.

Split out from app.main so routes.py can apply per-endpoint limits without a
circular import (main.py wires this into the FastAPI app; routes.py decorates
endpoints with it).
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

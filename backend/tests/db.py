"""Shared DB test helpers: reachability check and migration fixture."""

import socket

from sqlalchemy.engine import make_url

from app.core.config import settings


def database_reachable() -> bool:
    url = make_url(settings.database_url)
    host = url.host or "localhost"
    port = url.port or 5432
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex((host, port)) == 0

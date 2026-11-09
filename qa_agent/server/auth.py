"""Login & peran untuk mode server (sub-proyek 4)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

ROLES = ("admin", "qa", "viewer")
ROLE_LABEL = {"admin": "Admin", "qa": "QA", "viewer": "Viewer"}
COOKIE = "qa_session"
CSRF_HEADER = "X-QA-Agent"
SESSION_TTL = 12 * 3600  # keluar otomatis setelah 12 jam tidak aktif
SESSION_MAX_AGE = 7 * 24 * 3600
ITERATIONS = 600_000
MIN_PASSWORD = 8

# Perubahan data di area ini hanya untuk Admin
ADMIN_WRITE_PREFIXES = ("/api/profiles", "/api/skills", "/api/settings", "/api/users")
ADMIN_READ_PREFIXES = ("/api/users",)
QA_ALLOWED_WRITES = ("/api/skills/preview",)
PUBLIC_PATHS = ("/api/auth/status", "/api/auth/login")
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(ITERATIONS, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iterations, salt, digest = encoded.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    calc = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(iterations))
    return hmac.compare_digest(calc, base64.b64decode(digest))


class LoginLimiter:
    """Maksimal 5 percobaan gagal per username dalam 5 menit."""

    def __init__(self, limit: int = 5, window: float = 300) -> None:
        self.limit, self.window = limit, window
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque[float]:
        q = self._fails[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, username: str) -> bool:
        with self._lock:
            return len(self._trim(username.lower(), time.time())) >= self.limit

    def fail(self, username: str) -> None:
        with self._lock:
            self._trim(username.lower(), time.time()).append(time.time())

    def reset(self, username: str) -> None:
        with self._lock:
            self._fails.pop(username.lower(), None)


def permission_error(role: str, method: str, path: str) -> str | None:
    """Pesan bila peran tidak boleh mengakses; None bila boleh."""
    write = method in WRITE_METHODS
    if role == "admin":
        return None
    if path.startswith(ADMIN_READ_PREFIXES):
        return "Hanya Admin yang bisa mengelola pengguna"
    if not write:
        return None
    if path.startswith(("/api/auth/",)):
        return None
    if role == "viewer":
        return "Peran Viewer hanya bisa melihat dan mengunduh dokumen"
    if path.startswith(ADMIN_WRITE_PREFIXES) and not path.startswith(QA_ALLOWED_WRITES):
        return "Hanya Admin yang bisa mengubah pengaturan ini"
    return None

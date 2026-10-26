"""Single owner access. Staff roles and external identity integrations come later."""

import hashlib
import hmac
import secrets
import threading
import time
from http.cookies import SimpleCookie


class Auth:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.attempts = {}

    def configured(self):
        with self.store.connect() as con:
            return bool(con.execute("SELECT value FROM settings WHERE key='owner_password'").fetchone())

    def session(self, headers):
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get("Cookie", ""))
            token = cookie["libra_session"].value
        except Exception:
            return None
        key = hashlib.sha256(token.encode()).hexdigest()
        with self.store.connect() as con:
            row = con.execute("SELECT * FROM sessions WHERE token_hash=? AND expires>?",
                              (key, time.time())).fetchone()
        return dict(row) if row else None

    def login(self, password, setup, ApiError):
        if not isinstance(password, str) or not 10 <= len(password) <= 128:
            raise ApiError(400, "Use an owner password between 10 and 128 characters.")
        with self.lock:
            now = time.time()
            self.attempts = {k: v for k, v in self.attempts.items() if k > now - 60}
            if len(self.attempts) >= 10:
                raise ApiError(429, "Too many attempts. Please wait one minute.")
            self.attempts[now] = True
            with self.store.connect() as con:
                con.execute("BEGIN IMMEDIATE")
                row = con.execute("SELECT value FROM settings WHERE key='owner_password'").fetchone()
                if setup:
                    if row:
                        raise ApiError(409, "Owner access is already configured. Sign in instead.")
                    salt = secrets.token_hex(16)
                    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                                            n=16384, r=8, p=1).hex()
                    con.execute("INSERT INTO settings VALUES('owner_password',?)", (salt + ":" + digest,))
                    self.store.audit(con, "owner_access_created", {})
                else:
                    if not row:
                        raise ApiError(409, "Create owner access first.")
                    salt, expected = row[0].split(":", 1)
                    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                                            n=16384, r=8, p=1).hex()
                    if not hmac.compare_digest(digest, expected):
                        raise ApiError(401, "Incorrect owner password.")
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
                con.execute("DELETE FROM sessions WHERE expires<=?", (now,))
                con.execute("INSERT INTO sessions VALUES(?,?,?)",
                            (hashlib.sha256(token.encode()).hexdigest(), csrf, now + 8 * 3600))
                self.store.audit(con, "owner_signed_in", {})
                self.attempts.clear()
        return token, csrf


def register(route, ApiError):
    @route("GET", "/api/session", public=True)
    def session(req, query, body):
        return {"configured": req.app.auth.configured(), "authenticated": bool(req.session),
                "csrf": req.session["csrf"] if req.session else None,
                "mode": "test", "timezone": "Africa/Lagos"}

    def sign_in(req, body, setup):
        token, csrf = req.app.auth.login(body.get("password"), setup, ApiError)
        req.extra_headers["Set-Cookie"] = (
            f"libra_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800")
        return {"authenticated": True, "csrf": csrf}

    @route("POST", "/api/auth/setup", public=True)
    def setup(req, query, body):
        return sign_in(req, body, True)

    @route("POST", "/api/auth/login", public=True)
    def login(req, query, body):
        return sign_in(req, body, False)

    @route("POST", "/api/auth/logout")
    def logout(req, query, body):
        with req.app.store.connect() as con:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (req.session["token_hash"],))
        req.extra_headers["Set-Cookie"] = "libra_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"
        return {"authenticated": False}

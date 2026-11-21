"""
Login and session handling for the management portal. Standard library only.

- Users live in portal_users.json (salted PBKDF2 password hashes, never plain text).
  Manage them with:  python manage_users.py add|passwd|list|remove
- A signed, HttpOnly cookie keeps people signed in for SESSION_HOURS.
- Every page and every data endpoint needs the cookie, except the login page.
- n8n and other machines can use the header  X-API-Key  when the environment variable
  CRM_API_KEY is set (the key is never sent to browsers).
- Too many wrong passwords lock that user and address out for a few minutes.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from store import configured, open_store

HERE = Path(__file__).resolve().parent
USERS_FILE = Path(os.environ.get("PORTAL_USERS", HERE / "portal_users.json"))
SECRET_FILE = HERE / ".portal_secret"
COOKIE = "crm_session"
SESSION_HOURS = int(os.environ.get("PORTAL_SESSION_HOURS", "8"))
ITERATIONS = 200_000
MIN_PASSWORD = int(os.environ.get("PORTAL_MIN_PASSWORD", "5"))  # shortest password accepted when one is set
MAX_FAILS, LOCK_SECONDS = 5, 600
PUBLIC = {"/login", "/auth/login", "/auth/logout", "/healthz", "/favicon.ico"}


# ------------------------------------------------------------------ passwords
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f"pbkdf2${ITERATIONS}${salt}${h}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, h = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters)).hex()
        return hmac.compare_digest(calc, h)
    except Exception:
        return False


DUMMY = hash_password("not-a-real-password")


USERS_OBJECT = "users.json"
USERS_TTL = 15  # seconds a loaded user list is reused
_users_cache = {"t": 0.0, "users": None}


def _file_users() -> list:
    if not USERS_FILE.exists():
        return []
    return json.loads(USERS_FILE.read_text(encoding="utf-8")).get("users", [])


def load_users() -> list:
    """Users come from portal_users.json, or, when CONFIG_BUCKET / CONFIG_DIR is set, from users.json
    in that store (created from portal_users.json the first time, with the user named admin as administrator)."""
    if not configured("CONFIG"):
        return _file_users()
    now = time.time()
    if _users_cache["users"] is not None and now - _users_cache["t"] < USERS_TTL:
        return _users_cache["users"]
    try:
        store = open_store("CONFIG")
        text = store.read_text(USERS_OBJECT)
        if text is None:
            users = _file_users()
            if users and not any(u.get("role") == "admin" for u in users):
                for u in users:
                    if u["username"].lower() == "admin":
                        u["role"] = "admin"
            store.write_text(USERS_OBJECT, json.dumps({"users": users}, indent=2))
        else:
            users = json.loads(text).get("users", [])
    except Exception as e:  # fail closed: nobody can sign in until the store is reachable
        print(f"[auth] cannot read users: {e}", flush=True)
        return _users_cache["users"] if _users_cache["users"] is not None else []
    _users_cache.update(t=now, users=users)
    return users


def save_users(users: list) -> None:
    if configured("CONFIG"):
        open_store("CONFIG").write_text(USERS_OBJECT, json.dumps({"users": users}, indent=2))
        _users_cache.update(t=time.time(), users=users)
    else:
        USERS_FILE.write_text(json.dumps({"users": users}, indent=2), encoding="utf-8")


def is_admin(user: dict) -> bool:
    return bool(user) and user.get("role") == "admin"


def _pv(user: dict) -> str:
    """Short fingerprint of the stored password hash: changing a password ends that user's old sessions."""
    return hashlib.sha256(user["password"].encode()).hexdigest()[:10]


def find_user(username: str):
    for u in load_users():
        if u["username"].lower() == username.strip().lower():
            return u
    return None


# ------------------------------------------------------------------ session cookie
def secret_key() -> bytes:
    env = os.environ.get("CRM_SECRET_KEY")
    if env:
        return env.encode()
    try:
        if not SECRET_FILE.exists():
            SECRET_FILE.write_text(secrets.token_hex(32))
        return SECRET_FILE.read_text().strip().encode()
    except OSError:  # read-only disk: sessions then end when the server restarts
        global _MEM
        try:
            return _MEM
        except NameError:
            _MEM = secrets.token_hex(32).encode()
            return _MEM


def make_token(user: dict) -> str:
    payload = {"u": user["username"], "n": user.get("name", user["username"]), "r": user.get("role", "viewer"),
               "exp": int(time.time()) + SESSION_HOURS * 3600, "p": _pv(user)}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(secret_key(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_token(token: str):
    try:
        body, sig = token.split(".")
        good = hmac.new(secret_key(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if data["exp"] < time.time():
            return None
        current = find_user(data["u"])  # user removed or password changed since the cookie was issued
        if current is None or data.get("p") != _pv(current):
            return None
        data["admin"] = is_admin(current)
        return data
    except Exception:
        return None


# ------------------------------------------------------------------ middleware
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in PUBLIC:
            return await call_next(request)
        key = os.environ.get("CRM_API_KEY")
        sent = request.headers.get("x-api-key")
        if key and sent and hmac.compare_digest(sent, key):
            request.state.user = {"u": "api-key", "n": "API key", "r": "service"}
            return await call_next(request)
        session = read_token(request.cookies.get(COOKIE, ""))
        if session:
            request.state.user = session
            return await call_next(request)
        wants_page = "text/html" in request.headers.get("accept", "") and not path.startswith(("/auth/", "/insights", "/docs"))
        if wants_page and request.method == "GET":
            return RedirectResponse(f"/login?next={quote(path)}", status_code=303)
        return JSONResponse({"detail": "Not signed in"}, status_code=401)


_fails = {}


def _locked(key):
    now = time.time()
    _fails[key] = [t for t in _fails.get(key, []) if now - t < LOCK_SECONDS]
    return len(_fails[key]) >= MAX_FAILS


def install(app):
    app.add_middleware(AuthMiddleware)

    @app.post("/auth/login", include_in_schema=False)
    async def login(request: Request):
        try:
            data = await request.json()
            username, password = str(data.get("username", "")), str(data.get("password", ""))
        except Exception:
            return JSONResponse({"detail": "Bad request"}, status_code=400)
        ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()
        key = (ip, username.lower())
        if _locked(key):
            return JSONResponse({"detail": "Too many attempts. Try again in a few minutes."}, status_code=429)
        user = find_user(username)
        ok = verify_password(password, user["password"] if user else DUMMY) and user is not None
        if not ok:
            _fails.setdefault(key, []).append(time.time())
            return JSONResponse({"detail": "Wrong username or password."}, status_code=401)
        _fails.pop(key, None)
        resp = JSONResponse({"ok": True, "name": user.get("name", user["username"])})
        secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        resp.set_cookie(COOKIE, make_token(user), max_age=SESSION_HOURS * 3600, httponly=True, samesite="lax", secure=secure, path="/")
        return resp

    @app.post("/auth/logout", include_in_schema=False)
    async def logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.get("/auth/me", include_in_schema=False)
    async def me(request: Request):
        u = request.state.user
        return {"username": u["u"], "name": u["n"], "role": u["r"], "admin": bool(u.get("admin"))}

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok"}

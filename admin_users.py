"""Administrator-only user management for the portal: list, add, change role, set password, remove.
Passwords are stored only as salted hashes. Every route needs a signed-in administrator."""
import re
import threading

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import auth_portal as a

router = APIRouter(prefix="/admin", include_in_schema=False)
NAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
ROLES = ("management", "admin")
MIN_PASSWORD = a.MIN_PASSWORD
_lock = threading.Lock()


def _err(msg, code=400):
    return JSONResponse({"detail": msg}, status_code=code)


def _guard(request: Request):
    u = getattr(request.state, "user", None)
    return None if (u and u.get("admin")) else _err("Administrators only.", 403)


async def _body(request: Request) -> dict:
    try:
        d = await request.json()
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _find(users, username):
    for u in users:
        if u["username"].lower() == username.lower():
            return u
    return None


def _admins(users):
    return [u for u in users if a.is_admin(u)]


def _public(u):
    return {"username": u["username"], "name": u.get("name", ""), "role": u.get("role", "management")}


@router.get("/users")
def list_users(request: Request):
    return _guard(request) or {"users": [_public(u) for u in sorted(a.load_users(), key=lambda x: x["username"].lower())]}


@router.post("/users")
async def add_user(request: Request):
    if (g := _guard(request)):
        return g
    d = await _body(request)
    username, name, role, pw = str(d.get("username", "")).strip(), str(d.get("name", "")).strip(), d.get("role", "management"), str(d.get("password", ""))
    if not NAME_RE.match(username):
        return _err("Username: 3 to 32 letters, numbers, dot, dash or underscore.")
    if role not in ROLES:
        return _err("Role must be management or admin.")
    if len(pw) < MIN_PASSWORD:
        return _err(f"Password must be at least {MIN_PASSWORD} characters.")
    with _lock:
        users = [dict(u) for u in a.load_users()]
        if _find(users, username):
            return _err("That username already exists.", 409)
        users.append({"username": username, "name": name or username, "role": role, "password": a.hash_password(pw)})
        a.save_users(users)
    return {"ok": True}


@router.post("/users/{username}/password")
async def set_password(username: str, request: Request):
    if (g := _guard(request)):
        return g
    pw = str((await _body(request)).get("password", ""))
    if len(pw) < MIN_PASSWORD:
        return _err(f"Password must be at least {MIN_PASSWORD} characters.")
    with _lock:
        users = [dict(u) for u in a.load_users()]
        u = _find(users, username)
        if not u:
            return _err("No such user.", 404)
        u["password"] = a.hash_password(pw)
        a.save_users(users)
    return {"ok": True}


@router.post("/users/{username}/role")
async def set_role(username: str, request: Request):
    if (g := _guard(request)):
        return g
    role = (await _body(request)).get("role")
    if role not in ROLES:
        return _err("Role must be management or admin.")
    with _lock:
        users = [dict(u) for u in a.load_users()]
        u = _find(users, username)
        if not u:
            return _err("No such user.", 404)
        u["role"] = role
        if not _admins(users):
            return _err("There must always be at least one administrator.", 409)
        a.save_users(users)
    return {"ok": True}


@router.delete("/users/{username}")
def remove_user(username: str, request: Request):
    if (g := _guard(request)):
        return g
    if username.lower() == request.state.user["u"].lower():
        return _err("You cannot remove your own account.", 409)
    with _lock:
        users = [dict(u) for u in a.load_users()]
        u = _find(users, username)
        if not u:
            return _err("No such user.", 404)
        users.remove(u)
        if not _admins(users):
            return _err("There must always be at least one administrator.", 409)
        a.save_users(users)
    return {"ok": True}

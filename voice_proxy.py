"""
Voice relay: the push-to-talk button posts the recorded audio here (same site, signed-in users only);
this server forwards it to your n8n webhook together with who is asking, and returns n8n's answer.

Why through the portal: the browser never learns the n8n address or secret, no CORS setup is needed,
and n8n gets the identity of the signed-in user from the server, not from the browser.

Environment variables:
  N8N_VOICE_URL      the n8n production webhook URL (https://.../webhook/voice-query). Unset = voice switched off.
  N8N_VOICE_SECRET   shared secret, sent to n8n in the header X-Voice-Secret (check it in n8n).
  N8N_VOICE_TIMEOUT  seconds to wait for n8n (default 60).
  VOICE_RATE_PER_MIN questions allowed per user per minute (default 12).

Contract with n8n (multipart/form-data POST):
  file  audio      the recording (webm, mp4 or ogg)
  field session    conversation id, so n8n can remember follow-up questions
  field user, name, role      the signed-in portal user
  field salesman_id           only when the user record has "salesman_id": use it to scope every tool call
n8n must answer with JSON:  {"transcript": "...", "answer": "...", "table": {"columns": [...], "rows": [[...]]}}
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from auth_portal import find_user

router = APIRouter()
MAX_BYTES = 3_000_000
EXT = {"audio/webm": "webm", "audio/mp4": "mp4", "audio/ogg": "ogg", "audio/wav": "wav", "audio/mpeg": "mp3", "audio/x-m4a": "m4a"}
_hits = {}


def _cfg():
    return (os.environ.get("N8N_VOICE_URL", "").strip(), os.environ.get("N8N_VOICE_SECRET", ""),
            int(os.environ.get("N8N_VOICE_TIMEOUT", "60")), int(os.environ.get("VOICE_RATE_PER_MIN", "12")))


def _one_line(v) -> str:
    return re.sub(r"[\r\n\"]", " ", str(v))[:200]


def _multipart(fields: dict, filename: str, content_type: str, data: bytes):
    b = uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{_one_line(v)}\r\n'.encode())
    out.append(f'--{b}\r\nContent-Disposition: form-data; name="audio"; filename="{filename}"\r\n'
               f'Content-Type: {content_type}\r\n\r\n'.encode() + data + b"\r\n")
    out.append(f"--{b}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={b}"


def _post(url, secret, timeout, body, ctype):
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": ctype, "X-Voice-Secret": secret, "User-Agent": "crm-portal-voice/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(1_000_000)


def _table(t):
    if not isinstance(t, dict) or not isinstance(t.get("columns"), list) or not isinstance(t.get("rows"), list):
        return None
    cols = [str(c)[:40] for c in t["columns"][:8]]
    rows = [[("" if v is None else str(v))[:120] for v in list(r)[:len(cols)]] for r in t["rows"][:50] if isinstance(r, (list, tuple))]
    return {"columns": cols, "rows": rows} if cols and rows else None


@router.get("/voice/status", include_in_schema=False)
def voice_status():
    here = Path(__file__).resolve().parent
    avatar = any((here / f"voice_avatar.{e}").exists() for e in ("png", "jpg", "jpeg", "webp"))
    return {"enabled": bool(_cfg()[0]), "avatar": avatar}


@router.post("/voice/ask", include_in_schema=False)
async def voice_ask(request: Request):
    url, secret, timeout, rate = _cfg()
    if not url:
        raise HTTPException(503, "The voice assistant is not switched on (N8N_VOICE_URL is not set).")
    user = getattr(request.state, "user", None) or {}
    if not user.get("u") or user.get("u") == "api-key":
        raise HTTPException(403, "Sign in as a user to use voice.")
    now = time.time()
    recent = [t for t in _hits.get(user["u"], []) if now - t < 60]
    if len(recent) >= rate:
        raise HTTPException(429, "Too many questions, wait a moment.")
    _hits[user["u"]] = recent + [now]

    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype not in EXT:
        raise HTTPException(415, "Unsupported audio format.")
    data = await request.body()
    if len(data) < 800:
        raise HTTPException(400, "The recording was too short.")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "The recording is too long. Keep questions short.")

    rec = find_user(user["u"]) or {}
    fields = {"session": request.headers.get("x-session", "")[:64] or uuid.uuid4().hex, "user": user["u"],
              "name": user.get("n", user["u"]), "role": user.get("r", "")}
    if rec.get("salesman_id") not in (None, ""):
        fields["salesman_id"] = rec["salesman_id"]
    body, mp = _multipart(fields, f"question.{EXT[ctype]}", ctype, data)
    try:
        raw = await run_in_threadpool(_post, url, secret, timeout, body, mp)
        out = json.loads(raw)
        if not isinstance(out, dict):
            raise ValueError("not an object")
    except urllib.error.HTTPError as e:
        raise HTTPException(502, f"The voice workflow returned an error ({e.code}).")
    except (urllib.error.URLError, TimeoutError):
        raise HTTPException(504, "The voice workflow did not answer in time.")
    except ValueError:
        raise HTTPException(502, "The voice workflow sent an unreadable reply.")
    return {"transcript": str(out.get("transcript", ""))[:1000], "answer": str(out.get("answer", ""))[:2000],
            "table": _table(out.get("table"))}

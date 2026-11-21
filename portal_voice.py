"""
The management portal plus the push-to-talk voice assistant. Nothing in the existing files is changed:
this entry point loads portal.py, adds the voice routes, and puts the button on the /portal page.

Run:  uvicorn portal_voice:app --host 0.0.0.0 --port 8002
Set N8N_VOICE_URL and N8N_VOICE_SECRET to switch the voice assistant on (see VOICE_README.md).
"""
from urllib.parse import parse_qsl, urlencode

from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from portal import app, HERE, NOCACHE
from voice_proxy import router as voice_router
from voice_tools import router as tools_router

app.include_router(voice_router)
app.include_router(tools_router)

BLANK = {"", "null", "undefined", "none"}


@app.middleware("http")
async def drop_blank_tool_params(request, call_next):
    """n8n fills some tool parameters from expressions; an empty one (for example salesman_id for a manager)
    is treated as 'not given' instead of causing an error."""
    if request.url.path.startswith("/tools/") and request.scope.get("query_string"):
        pairs = [(k, v) for k, v in parse_qsl(request.scope["query_string"].decode(), keep_blank_values=True)
                 if v.strip().lower() not in BLANK]
        request.scope["query_string"] = urlencode(pairs).encode()
    return await call_next(request)


# Replace the /portal page with the same page plus the voice button.
app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/portal"]


@app.get("/portal", include_in_schema=False)
def portal_with_voice():
    html = (HERE / "portal.html").read_text(encoding="utf-8")
    tag = '<script src="/voice-widget.js" defer></script>'
    html = html.replace("</body>", tag + "\n</body>", 1) if "</body>" in html else html + tag
    return HTMLResponse(html, headers=NOCACHE)


@app.get("/voice-avatar", include_in_schema=False)
def voice_avatar():
    """Optional photo for the assistant: put voice_avatar.png, .jpg or .webp next to portal.py."""
    for name, kind in (("voice_avatar.png", "image/png"), ("voice_avatar.jpg", "image/jpeg"),
                       ("voice_avatar.jpeg", "image/jpeg"), ("voice_avatar.webp", "image/webp")):
        if (HERE / name).exists():
            return FileResponse(HERE / name, media_type=kind, headers={"Cache-Control": "no-cache"})
    raise HTTPException(404, "No custom avatar")


@app.get("/voice-widget.js", include_in_schema=False)
def voice_widget():
    return FileResponse(HERE / "voice_widget.js", media_type="application/javascript", headers=NOCACHE)

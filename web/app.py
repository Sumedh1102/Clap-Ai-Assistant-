"""
Flask web interface for CLAP.

  /              CLAP HUD (React + ThreeUI PredictiveArcCanvas, built into web/frontend/dist)
  /console       text console: knowledge base import and task manifest
  /api/events    server-sent events: live assistant state, conversation, tool activity
  /api/state     current snapshot of the same data
  /api/system    real system metrics
  /api/chat      send a command (runs through the shared CLAP session)

Binds to 127.0.0.1 only. No secrets are ever sent to the browser.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
from pathlib import Path

from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory

from config import config
from database import load_recent_history
from events import hub
from tools.knowledge_base import (
    add_knowledge,
    delete_knowledge,
    import_claude_conversation,
    import_file,
    list_knowledge,
    search_knowledge,
)
from tools.tasks import list_tasks
from web.system import system_metrics

log = logging.getLogger("clap.web")

HUD_DIST = Path(__file__).resolve().parent / "frontend" / "dist"
SSE_KEEPALIVE_SECONDS = 15

app = Flask(__name__, template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB upload limit

_session = None
_session_lock = threading.Lock()


def get_session():
    """The CLAP session shared with voice mode; created on demand for web-only use."""
    global _session
    with _session_lock:
        if _session is None:
            from session import ClapSession
            _session = ClapSession(speak_replies=False, voice_mode=False)
        return _session


def set_session(session) -> None:
    global _session
    with _session_lock:
        _session = session


# ── Local-only guard ──────────────────────────────────────────────────────────

_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


@app.before_request
def _local_only():
    # Reject requests addressed to other hostnames (DNS-rebinding protection):
    # CLAP can open apps and send email, so only localhost may drive it.
    host = request.host or ""
    hostname = host.split("]")[0] + "]" if host.startswith("[") else host.rsplit(":", 1)[0]
    if hostname.lower() not in _ALLOWED_HOSTS:
        abort(403)


# ── Pages ────────────────────────────────────────────────────────────────────

_HUD_MISSING = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>CLAP</title><style>body{background:#030303;color:#d9d3ee;font:15px -apple-system,sans-serif;
display:grid;place-items:center;height:100vh;margin:0}code{color:#b9a8ff}</style></head>
<body><div><h1 style="letter-spacing:.4em;font-weight:500">CLAP</h1>
<p>The HUD has not been built yet. From the project folder run:</p>
<p><code>npm install &amp;&amp; npm run build</code></p>
<p>Then reload this page. The text console is available at <a style="color:#b9a8ff" href="/console">/console</a>.</p>
</div></body></html>"""


@app.route("/")
def index():
    if (HUD_DIST / "index.html").exists():
        return send_from_directory(HUD_DIST, "index.html", max_age=0)
    return Response(_HUD_MISSING, mimetype="text/html")


@app.route("/assets/<path:filename>")
def hud_assets(filename: str):
    return send_from_directory(HUD_DIST / "assets", filename)


@app.route("/console")
def console_page():
    return render_template("console.html", user_name=config.USER_NAME, model=config.MODEL)


# ── Live state ────────────────────────────────────────────────────────────────

def _static_info() -> dict:
    return {"assistant": config.ASSISTANT_NAME, "model": config.MODEL, "user_name": config.USER_NAME}


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@app.route("/api/events")
def api_events():
    q = hub.subscribe()

    def stream():
        try:
            yield "retry: 2000\n\n"
            yield _sse({**hub.snapshot(), **_static_info()})
            while True:
                try:
                    yield _sse(q.get(timeout=SSE_KEEPALIVE_SECONDS))
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            hub.unsubscribe(q)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/state")
def api_state():
    return jsonify({**hub.snapshot(), **_static_info()})


@app.route("/api/system")
def api_system():
    snap = hub.snapshot()
    return jsonify({
        **system_metrics(),
        "model": config.MODEL,
        "mic": snap["mic"],
        "voice": snap["voice"],
        "state": snap["state"],
        "busy": _session.busy if _session is not None else False,
    })


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "assistant": config.ASSISTANT_NAME})


# ── Chat ─────────────────────────────────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "No message provided"}), 400

    result = get_session().handle(message, source="web", wait=True)
    if result.ok:
        return jsonify({
            "ok": True,
            "reply": result.reply,
            "message_id": result.message_id,
            "spoken": result.spoken,
            "voice_error": result.error or None,
        })
    # The request was handled; the command's outcome is an assistant-level error
    # (already shown in the HUD via the event stream), so this is not an HTTP error.
    return jsonify({"ok": False, "error": result.error, "message_id": result.message_id})


@app.route("/api/chat/history", methods=["GET"])
def api_chat_history():
    history = load_recent_history(config.HISTORY_LIMIT)
    # Return only user/assistant text pairs for the web UI
    messages = []
    for msg in history:
        if isinstance(msg["content"], str):
            messages.append({"role": msg["role"], "content": msg["content"]})
        elif isinstance(msg["content"], list):
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    messages.append({"role": msg["role"], "content": block["text"]})
    return jsonify({"messages": messages})


# ── Knowledge base ────────────────────────────────────────────────────────────

@app.route("/api/kb", methods=["GET"])
def api_kb_list():
    return jsonify(list_knowledge(limit=100))


@app.route("/api/kb/search", methods=["POST"])
def api_kb_search():
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "No query provided"}), 400
    return jsonify(search_knowledge(query, n_results=10))


@app.route("/api/kb/add", methods=["POST"])
def api_kb_add():
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    title = (data.get("title") or "").strip()
    tags = (data.get("tags") or "").strip()
    if not content:
        return jsonify({"error": "Content is required"}), 400
    return jsonify(add_knowledge(content, title=title, tags=tags))


@app.route("/api/kb/<doc_id>", methods=["DELETE"])
def api_kb_delete(doc_id: str):
    return jsonify(delete_knowledge(doc_id))


@app.route("/api/kb/import/claude", methods=["POST"])
def api_kb_import_claude():
    data = request.get_json(silent=True) or {}
    json_text = (data.get("json_text") or "").strip()
    title = (data.get("title") or "").strip()
    if not json_text:
        return jsonify({"error": "json_text is required"}), 400
    return jsonify(import_claude_conversation(json_text, title=title))


@app.route("/api/kb/import/file", methods=["POST"])
def api_kb_import_file():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    # Save to a temp location, import, then delete
    import tempfile
    suffix = Path(f.filename).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        f.save(tmp.name)
        tmp_path = tmp.name

    try:
        result = import_file(tmp_path, title=Path(f.filename).stem)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return jsonify(result)


# ── Tasks ─────────────────────────────────────────────────────────────────────

@app.route("/api/tasks", methods=["GET"])
def api_tasks():
    status = request.args.get("status", "all")
    return jsonify(list_tasks(status=status))


# ── Runner ────────────────────────────────────────────────────────────────────

def run_web(port: int | None = None, open_browser: bool = True, session=None):
    """
    Start the web server in a background daemon thread and return it.
    Raises OSError immediately if the port is unavailable.
    """
    from werkzeug.serving import make_server

    if session is not None:
        set_session(session)
    port = config.WEB_PORT if port is None else port
    try:
        server = make_server("127.0.0.1", port, app, threaded=True)
    except SystemExit:
        # werkzeug exits the process when the port is taken; callers expect an error instead
        raise OSError(f"port {port} is already in use") from None
    threading.Thread(target=server.serve_forever, name="clap-web", daemon=True).start()
    log.info("HUD serving on http://127.0.0.1:%d", port)

    if open_browser:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{port}")
    return server

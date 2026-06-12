"""Starlette server speaking the subset of opencode's protocol the TUI needs.

Boot endpoints return a minimal catalog; ``/global/event`` is the SSE stream;
a prompt spawns mini-swe-agent in a worker thread whose steps stream back as
opencode message parts. Launch with ``mini-opencode`` then attach the real TUI.
"""

import argparse
import asyncio
import json
import logging
import os
import shlex
import subprocess
import tempfile
import threading
import time
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

from platformdirs import user_config_dir, user_state_dir
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from . import ids, protocol
from .state import Hub

hub = Hub()
_CWD = os.getcwd()
log = logging.getLogger("mini_opencode")
LOG_PATH = Path("/tmp/mini-opencode.log") if Path("/tmp").is_dir() else Path(tempfile.gettempdir()) / "mini-opencode.log"
_API_KEY_ENVS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY")


def _worktree() -> str:
    return _CWD


# --- SSE ---------------------------------------------------------------------
def _sse(event: dict) -> str:
    # The TUI's /global/event consumer expects a GlobalEvent envelope and drops anything whose
    # `directory` isn't "global" (or whose project doesn't match) — see opencode context/event.ts.
    return f"event: message\ndata: {json.dumps({'directory': 'global', 'payload': event})}\n\n"


async def global_event(request: Request) -> StreamingResponse:
    async def gen():
        q = hub.subscribe()
        try:
            yield _sse(protocol.event_server_connected())
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=10)
                    yield _sse(event)
                except asyncio.TimeoutError:
                    yield _sse(protocol.event_heartbeat())
        finally:
            hub.unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


# --- boot endpoints ----------------------------------------------------------
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "version": "0.0.0"})


async def config_get(_: Request) -> JSONResponse:
    return JSONResponse(protocol.config_response())


async def global_config_get(_: Request) -> JSONResponse:
    cfg = protocol.config_response()
    return JSONResponse({"model": cfg["model"], "provider": {}, "plugin": {}})


async def config_providers(_: Request) -> JSONResponse:
    return JSONResponse(protocol.config_providers_response())


async def provider_list(_: Request) -> JSONResponse:
    return JSONResponse(protocol.provider_list_response())


async def provider_auth(_: Request) -> JSONResponse:
    return JSONResponse({})


async def agents(_: Request) -> JSONResponse:
    return JSONResponse(protocol.agents_response())


async def project_current(_: Request) -> JSONResponse:
    return JSONResponse(protocol.project_current(_worktree()))


async def project_list(_: Request) -> JSONResponse:
    return JSONResponse([protocol.project_current(_worktree())])


async def path_get(_: Request) -> JSONResponse:
    return JSONResponse(
        protocol.path_info(
            worktree=_worktree(),
            directory=_CWD,
            home=str(Path.home()),
            state=user_state_dir("opencode"),
            config=user_config_dir("opencode"),
        )
    )


async def vcs_get(_: Request) -> JSONResponse:
    return JSONResponse({"branch": "main", "default_branch": "main"})


async def empty_list(_: Request) -> JSONResponse:
    return JSONResponse([])


async def empty_object(_: Request) -> JSONResponse:
    return JSONResponse({})


# --- sessions ----------------------------------------------------------------
async def session_list(_: Request) -> JSONResponse:
    return JSONResponse(hub.list_sessions())


async def session_create(request: Request) -> JSONResponse:
    body = await _json(request)
    sid = ids.session_id()
    s = protocol.session(sid, directory=_CWD, worktree=_worktree(), title=body.get("title", ""), parent_id=body.get("parentID"))
    model = body.get("model") or {}
    if model:
        s["model"] = {"providerID": model.get("providerID", protocol.DEFAULT_PROVIDER), "modelID": model.get("modelID") or model.get("id") or protocol.DEFAULT_MODEL}
    hub.put_session(s)
    hub.publish(protocol.event_session_updated(s))
    return JSONResponse(s)


async def session_get(request: Request) -> JSONResponse:
    s = hub.get_session(request.path_params["sessionID"])
    return JSONResponse(s) if s else JSONResponse({"error": "not found"}, status_code=404)


async def session_messages(request: Request) -> JSONResponse:
    return JSONResponse(hub.get_messages(request.path_params["sessionID"]))


async def session_abort(request: Request) -> JSONResponse:
    cancel = hub.cancels.get(request.path_params["sessionID"])
    if cancel:
        cancel.set()
    return JSONResponse(True)


async def session_prompt(request: Request) -> JSONResponse:
    sid = request.path_params["sessionID"]
    session = hub.get_session(sid)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    body = await _json(request)
    model = body.get("model") or session.get("model") or {}
    provider_id = model.get("providerID", protocol.DEFAULT_PROVIDER)
    model_id = model.get("modelID") or model.get("id") or protocol.DEFAULT_MODEL
    agent = body.get("agent", "build")
    text = "\n".join(p.get("text", "") for p in body.get("parts", []) if p.get("type") == "text").strip()
    log.info("prompt received sid=%s model=%s/%s text=%r", sid, provider_id, model_id, text[:120])

    # Use our own ID scheme for both user and assistant messages so they sort consistently
    # (the client-supplied messageID uses opencode's format and would mis-order against ours).
    user_id = ids.message_id()
    hub.publish(protocol.event_message_updated(protocol.user_message(user_id, sid, provider_id, model_id, agent)))
    hub.publish(protocol.event_part_updated(protocol.text_part(ids.part_id(), user_id, sid, text)))

    from . import bridge

    cancel = threading.Event()
    hub.cancels[sid] = cancel
    threading.Thread(
        target=bridge.run_prompt,
        args=(hub, session, user_id, text, provider_id, model_id, cancel),
        daemon=True,
    ).start()
    return JSONResponse(None)


async def _json(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:
        return {}


# --- app ---------------------------------------------------------------------
@asynccontextmanager
async def _lifespan(_: Starlette):
    hub.attach_loop(asyncio.get_running_loop())
    yield


routes = [
    Route("/global/event", global_event),
    Route("/event", global_event),
    Route("/global/health", health),
    Route("/global/config", global_config_get),
    Route("/config", config_get),
    Route("/config/providers", config_providers),
    Route("/provider", provider_list),
    Route("/provider/auth", provider_auth),
    Route("/agent", agents),
    Route("/skill", empty_list),
    Route("/command", empty_list),
    Route("/project/current", project_current),
    Route("/project", project_list),
    Route("/path", path_get),
    Route("/lsp", empty_list),
    Route("/mcp", empty_object),
    Route("/formatter", empty_list),
    Route("/vcs", vcs_get),
    Route("/session", session_list),
    Route("/session", session_create, methods=["POST"]),
    Route("/session/status", empty_object),
    Route("/session/{sessionID}", session_get),
    Route("/session/{sessionID}/message", session_messages),
    Route("/session/{sessionID}/message", session_prompt, methods=["POST"]),  # client.session.prompt() posts here
    Route("/session/{sessionID}/todo", empty_list),
    Route("/session/{sessionID}/diff", empty_list),
    Route("/session/{sessionID}/children", empty_list),
    Route("/session/{sessionID}/prompt_async", session_prompt, methods=["POST"]),
    Route("/session/{sessionID}/abort", session_abort, methods=["POST"]),
    Route("/log", empty_object, methods=["POST"]),
]

async def _log_requests(request: Request, call_next):
    response = await call_next(request)
    log.info("HTTP %s %s -> %s", request.method, request.url.path, response.status_code)
    return response


app = Starlette(
    routes=routes,
    lifespan=_lifespan,
    middleware=[Middleware(BaseHTTPMiddleware, dispatch=_log_requests)],
)


# --- launch ------------------------------------------------------------------
def _wait_healthy(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/global/health", timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.1)
    return False


def main() -> None:
    import uvicorn

    global _CWD
    parser = argparse.ArgumentParser(prog="mini-opencode", description="mini-swe-agent behind the opencode TUI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4747)
    parser.add_argument("--cwd", default=os.getcwd(), help="working directory the agent operates in")
    parser.add_argument("--attach", action="store_true", help="auto-launch `opencode attach` against this server")
    parser.add_argument(
        "--opencode-dir",
        default=None,
        help="dir to launch the TUI from (needed for the dev `bun src/index.ts` TUI so it loads opencode's tsconfig)",
    )
    args = parser.parse_args()
    _CWD = str(Path(args.cwd).resolve())
    url = f"http://{args.host}:{args.port}"

    # Attach our own file handler (basicConfig is a no-op once minisweagent configures the root logger).
    _fh = logging.FileHandler(LOG_PATH)
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(_fh)
    log.setLevel(logging.INFO)
    log.propagate = False
    have_key = [k for k in _API_KEY_ENVS if os.getenv(k)]
    if not have_key:
        print(
            "WARNING: no LLM API key in env (ANTHROPIC_API_KEY / OPENAI_API_KEY / ...). "
            "Agent turns will fail until you export one.",
            flush=True,
        )
    print(f"mini-opencode: cwd={_CWD}  log={LOG_PATH}", flush=True)
    log.info("starting cwd=%s keys=%s", _CWD, have_key or "NONE")

    if not args.attach:
        print(f"mini-opencode server on {url}\nAttach the TUI with:  opencode attach {url}", flush=True)
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
        return

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    if not _wait_healthy(url):
        print("server failed to start", flush=True)
        return
    # Resolve how to launch the TUI. Prefer the vendored standalone binary (self-contained —
    # no external opencode repo needed); OPENCODE_CMD overrides; else a global `opencode`.
    vendored = Path(__file__).resolve().parent / "bin" / "opencode"
    if os.getenv("OPENCODE_CMD"):
        opencode_cmd = shlex.split(os.environ["OPENCODE_CMD"])
    elif vendored.exists():
        opencode_cmd = [str(vendored)]
    else:
        opencode_cmd = ["opencode"]
    # The dev TUI (`bun .../packages/opencode/src/index.ts`) must launch from the opencode
    # package dir so bun loads its tsconfig (jsxImportSource=@opentui/solid). Infer it.
    attach_cwd = args.opencode_dir
    if not attach_cwd:
        for tok in opencode_cmd:
            if tok.endswith("index.ts") and "packages/opencode" in tok:
                attach_cwd = str(Path(tok).resolve().parents[1])
                break
    # No --dir: that triggers process.chdir() right before the TUI imports, re-breaking JSX
    # resolution. The session's working dir is controlled by this server's --cwd instead.
    try:
        subprocess.run([*opencode_cmd, "attach", url], check=False, cwd=attach_cwd)
    finally:
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    main()

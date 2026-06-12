"""Builders for the opencode JSON objects and the minimal boot catalog.

Every function returns plain dicts matching opencode's OpenAPI schemas closely
enough for its SDK/TUI (which does not runtime-validate responses) to consume.
The selected ``providerID/modelID`` maps directly to a litellm model string.
"""

import getpass
import hashlib
import re
import time

from . import ids

# --- model catalog -----------------------------------------------------------
# providerID/modelID -> litellm model name is just f"{providerID}/{modelID}".
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-sonnet-4-6"

# Always-present latest models (litellm's registry may lag behind these).
# providerID/modelID maps directly to a litellm model name (f"{providerID}/{modelID}").
_CURATED: dict[str, dict] = {
    "anthropic": {
        "name": "Anthropic",
        "models": {
            "claude-opus-4-7": {"name": "Claude Opus 4.7"},
            "claude-sonnet-4-6": {"name": "Claude Sonnet 4.6"},
            "claude-sonnet-4-5": {"name": "Claude Sonnet 4.5"},
            "claude-haiku-4-5": {"name": "Claude Haiku 4.5"},
        },
    },
    "openai": {
        "name": "OpenAI",
        "models": {
            "gpt-5.5-pro": {"name": "GPT-5.5 Pro"},
            "gpt-5.5": {"name": "GPT-5.5"},
            "gpt-5.5-codex": {"name": "GPT-5.5 Codex"},
        },
    },
    "gemini": {
        "name": "Google Gemini",
        "models": {
            "gemini-3-pro-preview": {"name": "Gemini 3 Pro"},
            "gemini-3-flash": {"name": "Gemini 3 Flash"},
        },
    },
}

_catalog_cache: dict[str, dict] | None = None


def _catalog() -> dict[str, dict]:
    """Comprehensive provider/model catalog: every chat model litellm knows + curated latest.

    Built lazily and cached. Falls back to the curated set if litellm is unavailable.
    """
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache
    catalog: dict[str, dict] = {pid: {"name": m["name"], "models": dict(m["models"])} for pid, m in _CURATED.items()}
    try:
        import litellm

        for key, info in litellm.model_cost.items():
            if not isinstance(info, dict) or info.get("mode") != "chat":
                continue
            provider = info.get("litellm_provider")
            if not provider or key in ("sample_spec",):
                continue
            model_id = key.split("/", 1)[1] if "/" in key else key
            catalog.setdefault(provider, {"name": provider, "models": {}})["models"].setdefault(
                model_id, {"name": model_id}
            )
    except Exception:
        pass
    _catalog_cache = catalog
    return catalog


def now_ms() -> int:
    return int(time.time() * 1000)


def litellm_model_name(provider_id: str, model_id: str) -> str:
    return f"{provider_id}/{model_id}"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "session"


def project_id_for(worktree: str) -> str:
    return hashlib.sha1(worktree.encode()).hexdigest()


# --- boot responses ----------------------------------------------------------
def _model_entry(model_id: str, meta: dict) -> dict:
    return {
        "id": model_id,
        "name": meta.get("name", model_id),
        "release_date": "",
        "attachment": False,
        "reasoning": False,
        "temperature": True,
        "tool_call": True,
        "cost": {"input": 0, "output": 0, "cache": {"read": 0, "write": 0}},
        "limit": {"context": 200000, "output": 32000},
        "options": {},
    }


def _provider_entry(provider_id: str) -> dict:
    meta = _catalog()[provider_id]
    return {
        "id": provider_id,
        "name": meta["name"],
        "env": [],
        "api": None,
        "npm": None,
        "models": {mid: _model_entry(mid, m) for mid, m in meta["models"].items()},
    }


def _default_map() -> dict[str, str]:
    return {pid: next(iter(meta["models"])) for pid, meta in _catalog().items()}


def config_providers_response() -> dict:
    return {"providers": [_provider_entry(p) for p in _catalog()], "default": _default_map()}


def provider_list_response() -> dict:
    return {"all": [_provider_entry(p) for p in _catalog()], "default": _default_map(), "connected": list(_catalog())}


def agents_response() -> list[dict]:
    return [
        {
            "name": "build",
            "description": "mini-swe-agent",
            "mode": "primary",
            "builtIn": True,
            "model": {"providerID": DEFAULT_PROVIDER, "modelID": DEFAULT_MODEL},
            "temperature": None,
            "tools": {},
            "permission": [],
            "options": {},
        }
    ]


def config_response() -> dict:
    return {
        "username": getpass.getuser(),
        "model": litellm_model_name(DEFAULT_PROVIDER, DEFAULT_MODEL),
        "agent": {},
        "provider": {},
    }


def project_current(worktree: str) -> dict:
    t = now_ms()
    return {
        "id": project_id_for(worktree),
        "worktree": worktree,
        "vcs": "git",
        "time": {"created": t, "updated": t},
        "sandboxes": [],
    }


def path_info(worktree: str, directory: str, home: str, state: str, config: str) -> dict:
    return {"home": home, "state": state, "config": config, "worktree": worktree, "directory": directory}


# --- sessions / messages / parts --------------------------------------------
def session(session_id: str, directory: str, worktree: str, title: str = "", parent_id: str | None = None) -> dict:
    t = now_ms()
    s = {
        "id": session_id,
        "slug": _slug(title) if title else session_id,
        "projectID": project_id_for(worktree),
        "directory": directory,
        "title": title or "mini-swe-agent",
        "version": "0.0.0",
        "time": {"created": t, "updated": t},
    }
    if parent_id:
        s["parentID"] = parent_id
    return s


def user_message(message_id: str, session_id: str, provider_id: str, model_id: str, agent: str = "build") -> dict:
    return {
        "id": message_id,
        "sessionID": session_id,
        "role": "user",
        "time": {"created": now_ms()},
        "agent": agent,
        "model": {"providerID": provider_id, "modelID": model_id},
    }


def assistant_message(
    message_id: str,
    session_id: str,
    parent_id: str,
    provider_id: str,
    model_id: str,
    cwd: str,
    root: str,
    agent: str = "build",
) -> dict:
    return {
        "id": message_id,
        "sessionID": session_id,
        "role": "assistant",
        "parentID": parent_id,
        "time": {"created": now_ms()},
        "modelID": model_id,
        "providerID": provider_id,
        "mode": agent,
        "agent": agent,
        "path": {"cwd": cwd, "root": root},
        "cost": 0,
        "tokens": {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}},
    }


def text_part(part_id: str, message_id: str, session_id: str, text: str) -> dict:
    return {
        "id": part_id,
        "sessionID": session_id,
        "messageID": message_id,
        "type": "text",
        "text": text,
        "time": {"start": now_ms()},
    }


def tool_part(
    part_id: str,
    message_id: str,
    session_id: str,
    call_id: str,
    command: str,
    *,
    state: dict,
) -> dict:
    return {
        "id": part_id,
        "sessionID": session_id,
        "messageID": message_id,
        "type": "tool",
        "callID": call_id,
        "tool": "bash",
        "state": state,
    }


def tool_state_running(command: str, start: int) -> dict:
    return {
        "status": "running",
        "input": {"command": command},
        "title": command.strip().splitlines()[0][:80] if command.strip() else "bash",
        "metadata": {},
        "time": {"start": start},
    }


def tool_state_completed(command: str, output: str, start: int, returncode: int | None = None) -> dict:
    return {
        "status": "completed",
        "input": {"command": command},
        "output": output,
        "title": command.strip().splitlines()[0][:80] if command.strip() else "bash",
        "metadata": {"returncode": returncode} if returncode is not None else {},
        "time": {"start": start, "end": now_ms()},
    }


def step_start_part(part_id: str, message_id: str, session_id: str) -> dict:
    return {"id": part_id, "sessionID": session_id, "messageID": message_id, "type": "step-start"}


# --- events ------------------------------------------------------------------
def _event(event_type: str, properties: dict) -> dict:
    return {"id": ids.event_id(), "type": event_type, "properties": properties}


def event_server_connected() -> dict:
    return _event("server.connected", {})


def event_heartbeat() -> dict:
    return _event("server.heartbeat", {})


def event_message_updated(info: dict) -> dict:
    return _event("message.updated", {"info": info, "sessionID": info["sessionID"]})


def event_part_updated(part: dict) -> dict:
    return _event("message.part.updated", {"part": part, "sessionID": part["sessionID"]})


def event_session_updated(info: dict) -> dict:
    return _event("session.updated", {"info": info, "sessionID": info["id"]})


def event_session_idle(session_id: str) -> dict:
    return _event("session.idle", {"sessionID": session_id})


def event_session_error(session_id: str, message: str) -> dict:
    return _event("session.error", {"sessionID": session_id, "error": {"name": "Error", "data": {"message": message}}})

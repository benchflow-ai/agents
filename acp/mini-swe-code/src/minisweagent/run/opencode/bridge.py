"""Bridge mini-swe-agent's loop onto opencode's message/part event stream.

``OpencodeBridgeAgent`` subclasses ``DefaultAgent`` and, instead of changing the
loop, hooks ``query``/``execute_actions`` to emit opencode events: one assistant
message per turn, with a step-start + text + bash tool part per step (tool state
goes running -> completed). The agent runs in a worker thread; events are pushed
through the thread-safe ``Hub.publish``.
"""

import copy
import logging
import threading

from minisweagent.agents.default import DefaultAgent
from minisweagent.config import builtin_config_dir, get_config_from_spec
from minisweagent.environments import get_environment
from minisweagent.exceptions import Submitted
from minisweagent.models import get_model
from minisweagent.models.utils.content_string import get_content_string

from . import ids, protocol

log = logging.getLogger("mini_opencode")

_AGENT_CONFIG_KEYS = {"system_template", "instance_template", "step_limit", "cost_limit", "wall_time_limit_seconds"}


class OpencodeBridgeAgent(DefaultAgent):
    def __init__(self, *args, hub, session, parent_id, provider_id, model_id, cancel, **kwargs):
        super().__init__(*args, **kwargs)
        self.hub = hub
        self.session = session
        self.sid = session["id"]
        self.parent_id = parent_id
        self.provider_id = provider_id
        self.model_id = model_id
        self.cancel: threading.Event = cancel
        self.assistant_id: str | None = None
        self._assistant: dict | None = None
        self._tool_part_ids: dict[str, str] = {}
        self._tokens = {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}}

    # --- emit helpers ---
    def _ensure_assistant(self) -> None:
        if self.assistant_id:
            return
        self.assistant_id = ids.message_id()
        self._assistant = protocol.assistant_message(
            self.assistant_id,
            self.sid,
            self.parent_id,
            self.provider_id,
            self.model_id,
            cwd=self.session["directory"],
            root=self.session["directory"],
        )
        self._emit_assistant()

    def _emit_assistant(self) -> None:
        # snapshot: the same dict keeps mutating across the turn
        self.hub.publish(protocol.event_message_updated(copy.deepcopy(self._assistant)))

    def _refresh_assistant(self, *, completed: bool = False) -> None:
        if not self._assistant:
            return
        self._assistant["cost"] = round(self.cost, 6)
        self._assistant["tokens"] = self._tokens
        if completed:
            self._assistant["time"]["completed"] = protocol.now_ms()
        self._emit_assistant()

    def _accumulate_tokens(self, message: dict) -> None:
        usage = ((message.get("extra") or {}).get("response") or {}).get("usage") or {}
        self._tokens["input"] += usage.get("prompt_tokens") or 0
        self._tokens["output"] += usage.get("completion_tokens") or 0

    def _part(self, part: dict) -> None:
        self.hub.publish(protocol.event_part_updated(part))

    # --- overridden loop hooks ---
    def query(self) -> dict:
        if self.cancel.is_set():
            raise Submitted({"role": "exit", "content": "Aborted by user.", "extra": {"exit_status": "Aborted", "submission": ""}})
        self._ensure_assistant()
        self._part(protocol.step_start_part(ids.part_id(), self.assistant_id, self.sid))
        message = super().query()
        self._accumulate_tokens(message)
        text = get_content_string(message)
        if text and text.strip():
            self._part(protocol.text_part(ids.part_id(), self.assistant_id, self.sid, text))
        for action in (message.get("extra") or {}).get("actions", []):
            cid = action.get("tool_call_id") or ids.call_id()
            pid = ids.part_id()
            self._tool_part_ids[cid] = pid
            state = protocol.tool_state_running(action["command"], protocol.now_ms())
            self._part(protocol.tool_part(pid, self.assistant_id, self.sid, cid, action["command"], state=state))
        self._refresh_assistant()
        return message

    def execute_actions(self, message: dict) -> list[dict]:
        actions = (message.get("extra") or {}).get("actions", [])
        outputs: list[dict] = []
        for action in actions:
            cid = action.get("tool_call_id") or ids.call_id()
            pid = self._tool_part_ids.get(cid) or ids.part_id()
            start = protocol.now_ms()
            try:
                output = self.env.execute(action)
            except Submitted:
                self._part(
                    protocol.tool_part(
                        pid, self.assistant_id, self.sid, cid, action["command"],
                        state=protocol.tool_state_completed(action["command"], "Task submitted.", start, 0),
                    )
                )
                raise
            outputs.append(output)
            self._part(
                protocol.tool_part(
                    pid, self.assistant_id, self.sid, cid, action["command"],
                    state=protocol.tool_state_completed(
                        action["command"], output.get("output", ""), start, output.get("returncode")
                    ),
                )
            )
        return self.add_messages(*self.model.format_observation_messages(message, outputs, self.get_template_vars()))

    def finalize(self, error: str | None = None) -> None:
        if self._assistant is not None:
            if error:
                self._assistant["error"] = {"name": "Error", "data": {"message": error}}
            self._refresh_assistant(completed=True)
        self.hub.publish(protocol.event_session_idle(self.sid))

    def emit_error_text(self, message: str) -> None:
        """Make a failure visible in the TUI as assistant text (not just the error field)."""
        self._ensure_assistant()
        self._part(protocol.text_part(ids.part_id(), self.assistant_id, self.sid, f"⚠️  {message}"))
        self.finalize(error=message)


def build_agent(hub, session, parent_id, provider_id, model_id, cancel) -> OpencodeBridgeAgent:
    cfg = get_config_from_spec(str(builtin_config_dir / "mini.yaml"))
    model_cfg = dict(cfg.get("model", {}))
    model_cfg["model_name"] = protocol.litellm_model_name(provider_id, model_id)
    model_cfg.setdefault("cost_tracking", "ignore_errors")  # don't crash a turn when litellm lacks pricing
    model = get_model(config=model_cfg)
    env_cfg = dict(cfg.get("environment", {}))
    env_cfg["cwd"] = session["directory"]
    env = get_environment(env_cfg, default_type="local")
    agent_kwargs = {k: v for k, v in cfg.get("agent", {}).items() if k in _AGENT_CONFIG_KEYS}
    return OpencodeBridgeAgent(
        model, env, hub=hub, session=session, parent_id=parent_id,
        provider_id=provider_id, model_id=model_id, cancel=cancel, **agent_kwargs,
    )


def run_prompt(hub, session, parent_id, task, provider_id, model_id, cancel) -> None:
    """Worker-thread entrypoint: build the agent and run mini's loop to completion."""
    log.info("agent start sid=%s model=%s/%s", session["id"], provider_id, model_id)
    agent = None
    try:
        agent = build_agent(hub, session, parent_id, provider_id, model_id, cancel)
        agent.run(task)
        agent.finalize()
        log.info("agent done sid=%s cost=%.4f", session["id"], agent.cost)
    except Exception as e:  # model/auth/runtime errors that mini re-raises
        log.exception("agent error sid=%s", session["id"])
        hub.publish(protocol.event_session_error(session["id"], str(e)))
        if agent is not None:
            agent.emit_error_text(str(e))
        else:
            hub.publish(protocol.event_session_idle(session["id"]))

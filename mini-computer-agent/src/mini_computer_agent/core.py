"""mini-computer-agent core — a ~100-line computer-use agent.

The computer-use analog of mini-swe-agent: one screenshot, one vision-model call,
one action, repeat. No vendor computer-use tool, no separate grounding model,
no tool-calling interface — just a linear message history and ``subprocess``.
Runs with *any* vision model via litellm. Framework-free; the ACP shim wraps it.

    from mini_computer_agent.core import run
    run("Open the calculator and compute 2+2", model="gemini/gemini-3.5-flash")
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from typing import Any

SYSTEM_PROMPT = """\
You control a Linux desktop. Each turn you receive a screenshot. Reply with ONE
JSON object and nothing else. Coordinates x,y are integers in a 0-1000 normalized
space (0,0 = top-left, 1000,1000 = bottom-right), independent of resolution.

  {"action":"click","x":INT,"y":INT}
  {"action":"double_click","x":INT,"y":INT}
  {"action":"right_click","x":INT,"y":INT}
  {"action":"type","text":STR}
  {"action":"key","keys":STR}        (xdotool key spec, e.g. "ctrl+s")
  {"action":"scroll","dy":INT}       (negative = up, positive = down)
  {"action":"done","result":STR}     (STR = your final answer)

Think briefly, then act. One small action per turn; you'll see the result next.

Guidance:
- To enter text: first "click" the target field to focus it, then "type". Don't
  retype if the field already shows the right text.
- Before "done" or pressing a submit/OK button, check the latest screenshot
  actually shows the goal satisfied; if not, fix it first."""

_CLICK_BUTTON = {
    "click": ["1"],
    "double_click": ["--repeat", "2", "1"],
    "right_click": ["3"],
}


def _xenv() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":1")
    home = os.path.expanduser("~/.Xauthority")
    if os.path.isfile(home):
        env.setdefault("XAUTHORITY", home)
    return env


def _png_size(data: bytes) -> tuple[int, int]:
    """(width, height) from a PNG IHDR; (0, 0) if not a PNG."""
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return (0, 0)


def screenshot(path: str = "/tmp/mca.png") -> bytes:
    subprocess.run(["scrot", "-o", path], check=True, timeout=20, env=_xenv())
    with open(path, "rb") as f:
        return f.read()


def parse_action(text: str) -> dict[str, Any]:
    """First JSON object in the model reply (tolerates fences / surrounding prose)."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON action in reply: {text[:120]!r}")
    action = json.loads(m.group(0))
    if "action" not in action:
        raise ValueError(f"action object missing 'action' key: {action!r}")
    return action


def scale(nx: int, ny: int, width: int, height: int) -> tuple[int, int]:
    """[0,1000]-normalized -> pixels. Vision models (Gemini) emit 0-1000; using
    them raw mis-clicks by ~resolution/1000 (~3x), which reads as 'can't ground'
    when the model is actually correct. width/height 0 -> pass through (unknown)."""
    x = round(nx / 1000 * width) if width else nx
    y = round(ny / 1000 * height) if height else ny
    return x, y


def execute(action: dict[str, Any], width: int, height: int) -> None:
    """Run one action via xdotool. Coords are [0,1000]-normalized -> pixels."""
    kind = str(action["action"]).lower()
    if kind in _CLICK_BUTTON:
        x, y = scale(int(action["x"]), int(action["y"]), width, height)
        _xdotool("mousemove", "--sync", str(x), str(y), "click", *_CLICK_BUTTON[kind])
    elif kind == "type":
        _xdotool("type", "--clearmodifiers", "--", str(action.get("text", "")))
    elif kind == "key":
        _xdotool("key", "--clearmodifiers", str(action["keys"]))
    elif kind == "scroll":
        dy = int(action.get("dy", 0))
        for _ in range(max(1, abs(dy))):
            _xdotool("click", "4" if dy < 0 else "5")
    else:
        raise ValueError(f"unsupported action: {kind!r}")


def _xdotool(*args: str) -> None:
    subprocess.run(["xdotool", *args], check=True, timeout=20, env=_xenv())


def run(
    task: str,
    model: str,
    *,
    max_steps: int = 15,
    model_kwargs: dict[str, Any] | None = None,
    on_step: Callable[[int, str, dict[str, Any] | None], None] | None = None,
) -> str:
    """Drive the screenshot -> model -> action loop. Returns the final result.

    ``on_step(step, reply_text, action)`` is called each turn for trajectory
    capture (the ACP shim re-emits it as session/update); ``action`` is None on
    a parse failure. Pure stdlib + litellm; no benchflow import.
    """
    import litellm  # lazy: keeps parse_action/scale/_png_size testable without it

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Task: {task}"},
    ]
    for step in range(max_steps):
        data = screenshot()
        width, height = _png_size(data)
        b64 = base64.b64encode(data).decode()
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Screenshot (step {step})"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        )
        reply = (
            litellm.completion(
                model=model, messages=messages, max_tokens=1024, **(model_kwargs or {})
            )
            .choices[0]
            .message.content
            or ""
        )
        messages.append({"role": "assistant", "content": reply})
        try:
            action: dict[str, Any] | None = parse_action(reply)
        except ValueError:
            action = None
        if on_step:
            on_step(step, reply, action)
        if action is None:
            messages.append(
                {"role": "user", "content": "Reply with ONE JSON action object."}
            )
            continue
        if str(action["action"]).lower() == "done":
            return str(action.get("result", ""))
        execute(action, width, height)
        time.sleep(1.0)
    return "FAIL: step budget exhausted"

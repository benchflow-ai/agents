"""Hermetic tests for the mini-computer-agent core.

No sandbox, no model, no benchflow — pure action parsing + coordinate scaling.
``litellm`` is imported lazily inside ``run``, so these load without it.
"""

import struct

import pytest

from mini_computer_agent.core import _png_size, parse_action, scale


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"action":"click","x":500,"y":500}', {"action": "click", "x": 500, "y": 500}),
        (
            '```json\n{"action":"done","result":"ok"}\n```',
            {"action": "done", "result": "ok"},
        ),
        (
            'reasoning...\n{"action":"type","text":"hi"} trailing',
            {"action": "type", "text": "hi"},
        ),
    ],
)
def test_parse_action_ok(raw: str, expected: dict) -> None:
    assert parse_action(raw) == expected


@pytest.mark.parametrize("raw", ["no json here", '{"x":1}'])
def test_parse_action_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_action(raw)


def test_scale_normalized_1000_to_pixels() -> None:
    # Guards the coordinate-convention fix: vision models (Gemini) emit [0,1000]
    # coords; the core scales to the screenshot resolution before xdotool — using
    # them raw mis-clicks by ~resolution/1000 (~3x), which reads as "can't ground".
    assert scale(500, 500, 1280, 800) == (640, 400)
    assert scale(220, 455, 1280, 800) == (282, 364)  # the red-circle case
    assert scale(100, 200, 0, 0) == (100, 200)  # unknown size -> pass-through


def test_png_size() -> None:
    hdr = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 1280, 800)
    assert _png_size(hdr) == (1280, 800)
    assert _png_size(b"not a png") == (0, 0)

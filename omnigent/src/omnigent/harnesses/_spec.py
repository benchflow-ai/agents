"""The per-harness spec dataclass — one ``HarnessSpec`` per omnigent harness.

This mirrors how omnigent itself organises harness metadata: a canonical
``--harness`` value + aliases (omnigent's ``harness_aliases.py``) and a registry
that maps each to its wiring (omnigent's ``runtime.harnesses._HARNESS_MODULES``).
Here each harness's row lives in its own module under :mod:`omnigent.harnesses`
(one file per harness, like omnigent's ``inner/*_harness.py``), and the package
``__init__`` collects them into the single source of truth the registry +
factories derive from.

The BenchFlow adapter has NO per-harness logic (``OmnigentAgent.connect`` is
uniform — it writes one gateway ``config.yaml`` and omnigent's own runner routes
each harness to its provider family), so a ``HarnessSpec`` is pure data.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HarnessSpec:
    """Everything the BenchFlow registry needs to know about one omnigent harness.

    :param slug: BenchFlow agent name suffix — registers as ``omnigent-<slug>``;
        the per-harness session_factory is ``build_omnigent_<slug_underscored>``.
        Equals ``harness_value`` except where omnigent's alias differs (``claude``
        → ``claude-sdk``).
    :param harness_value: the literal ``omnigent run --harness <value>`` argument
        (omnigent's canonical harness name).
    :param wire: the harness's transport, informational —
        ``anthropic-messages`` | ``openai-chat`` | ``openai-responses`` |
        ``pi-gateway`` | ``vendor``.
    :param native: True when omnigent lists it in ``NATIVE_HARNESSES`` (its own
        driver bridging a resident TUI, no vendor SDK) — every ``*-native``.
    :param gateway_served: True when omnigent applies OUR ``config.yaml`` gateway
        provider to this harness — i.e. its ``harness_value`` is in omnigent's
        ``provider_config._HARNESS_FAMILY`` with an ``openai``/``anthropic`` family
        (plus ``pi``, handled by ``_apply_provider_to_pi``). False means our
        provider is silently ignored and the harness needs its own vendor backend.
    :param status: honest wiring status — ``worked`` (verified reward 1.0) |
        ``runs`` (e2e, llm_trajectory captured, reward < 1.0) | ``blocked`` (our
        provider is applied but the wire is not served, e.g. Responses) | ``wip``
        (provider applied, launches, not yet a scoreable run) | ``needs-vendor``
        (provider not applied — needs a vendor CLI + API key the gateway lacks).
    :param note: human-facing CLI/status detail (the old ``cli_note``).
    :param install: a POSIX-sh snippet appended to ``OMNIGENT_INSTALL_CMD`` to
        provision this harness's extra CLI, or ``None`` when the base install
        already covers it (pi) / it is a bundled in-process SDK (openai-agents) /
        its vendor CLI is not auto-installed.
    """

    slug: str
    harness_value: str
    wire: str
    native: bool
    gateway_served: bool
    status: str
    note: str
    install: str | None = None

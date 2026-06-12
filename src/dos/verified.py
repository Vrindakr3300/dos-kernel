"""dos.verified — run a code path only against verified work (issue #75).

The truth syscall (`dos verify` / `oracle.is_shipped`) answers "did this
(plan, phase) actually ship?" from git evidence, never from a worker's
self-report. Until now that verdict reached Python code only where someone
remembered to call it — opt-in at every call site. This helper turns the
step into a structural property: decorate a function (or open a context)
with the claim it depends on, and the body runs ONLY when the oracle
confirms the claim. Otherwise a typed `NotShippedError` carrying the full
`ShipVerdict` is raised, so "remember to verify" becomes "cannot forget
to verify" for in-process Python consumers — on any framework, or none.

Layer: a HELPER (CLAUDE.md row 3) — a thin shell over `oracle.is_shipped`
carrying no policy of its own and making no verdict the kernel doesn't
already make. The raise happens in the CALLER's process, so the kernel's
advisory-only posture is untouched: DOS still only decides; the user's own
code is what refuses to run.

Adjudication is at CALL time, not decoration time. A decorator is applied
at import, usually before the work it gates has shipped; each call
re-reads the evidence, so the gate opens the moment the phase verifiably
lands and never before.

    from dos import verified

    @verified("AUTH", "AUTH2", workspace="/path/to/repo")
    def publish_release_notes(): ...

    with verified("AUTH", "AUTH1", cfg=my_cfg) as verdict:
        ...  # runs only if SHIPPED; verdict.source names the rung

Config resolution, highest precedence first (the one library rule from the
Python cookbook): explicit ``cfg=`` › ``workspace=`` (that repo's
`dos.toml` folded in via `config.load_workspace_config`, loaded once and
cached on the gate) › the process-active config (`config.active()`),
re-resolved at every check so a host's later `set_active(...)` is honored.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Callable, TypeVar

from dos import config as _config
from dos import oracle as _oracle

__all__ = ["verified", "NotShippedError"]

_F = TypeVar("_F", bound=Callable[..., Any])


class NotShippedError(RuntimeError):
    """The gated claim did not verify — the body was refused.

    Carries the full `ShipVerdict` as ``.verdict`` so a caller can read
    WHICH rung answered (``verdict.source``) and what was asked
    (``verdict.plan``, ``verdict.phase``), not just that the gate refused.
    """

    def __init__(self, verdict: _oracle.ShipVerdict):
        self.verdict = verdict
        source = verdict.source or "none"
        super().__init__(
            f"({verdict.plan}, {verdict.phase}) NOT_SHIPPED (via {source}) — "
            "the truth syscall found no evidence this claim landed; "
            "refusing to run the gated body"
        )


class verified:
    """Gate a code path on the truth syscall — decorator and context manager.

    ``verified(plan, phase)`` is one claim, adjudicated by
    `oracle.is_shipped` each time the gate is crossed. As a decorator the
    check runs on every call of the wrapped function; as a context manager
    it runs on ``__enter__`` and yields the SHIPPED verdict. Either way a
    failed check raises `NotShippedError` — the body never runs on an
    unverified claim.
    """

    def __init__(
        self,
        plan: str,
        phase: str,
        *,
        cfg: "_config.SubstrateConfig | None" = None,
        workspace: str | Path | None = None,
    ):
        if cfg is not None and workspace is not None:
            raise TypeError("pass cfg= or workspace=, not both")
        self.plan = str(plan)
        self.phase = str(phase)
        self._cfg = cfg
        self._workspace = workspace

    def _resolve_config(self) -> "_config.SubstrateConfig":
        if self._cfg is not None:
            return self._cfg
        if self._workspace is not None:
            # Load the workspace's dos.toml once and keep it — the same
            # readback the CLI does (`load_workspace_config`), cached so a
            # hot decorated function doesn't re-parse TOML on every call.
            self._cfg = _config.load_workspace_config(self._workspace)
            return self._cfg
        # Ambient default, resolved per check (never cached) so a host that
        # calls `set_active(...)` after this gate was built is still honored.
        return _config.active()

    def check(self) -> _oracle.ShipVerdict:
        """Adjudicate now: return the SHIPPED verdict or raise `NotShippedError`."""
        verdict = _oracle.is_shipped(self.plan, self.phase, cfg=self._resolve_config())
        if not verdict.shipped:
            raise NotShippedError(verdict)
        return verdict

    # ---- decorator form ----------------------------------------------------
    def __call__(self, fn: _F) -> _F:
        @functools.wraps(fn)
        def gated(*args: Any, **kwargs: Any) -> Any:
            self.check()
            return fn(*args, **kwargs)

        # Introspectable: which claim gates this function (tooling can read
        # the gate without calling through it).
        gated.__dos_verified__ = self  # type: ignore[attr-defined]
        return gated  # type: ignore[return-value]

    # ---- context-manager form ------------------------------------------------
    def __enter__(self) -> _oracle.ShipVerdict:
        return self.check()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

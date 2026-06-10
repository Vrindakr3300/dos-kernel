"""The no-good verdict-token registry — the rewind note's closed vocabulary, *as data*.

docs/164 §6 (the F1.5 conversation-rewind axis). When the kernel rewinds a
conversation to a minted checkpoint, the agent re-enters with a **no-good
annotation**. The single load-bearing rule of that annotation (docs/164 §1, §6)
is that it may carry **only un-forged bytes** — and the most dangerous failure
mode is the one `BLOCK` died of: a *generated* explanation of why the branch
failed ("you should have used a try/except") sneaking in as a note byte. That is
the forgeable rung; it belongs to F3, behind the apply-gate PEP, never to F1.5.

This module is the structural lock that makes that impossible. It is the
`reasons.py` `ReasonRegistry` pattern (the closed-enum-as-data hackability seam,
`docs/HACKING.md`) re-aimed at the no-good vocabulary: the *mechanism* (a token
RENDERS via a registry-owned template over structured fields the kernel computed)
lives here; the *set of token kinds* is a closed, ordered, immutable registry. A
`VerdictToken` is **not a string** — it is a frozen `(kind, payload)` where `kind`
is drawn from the registry and the rendered string is COMPOSED from the registry's
own template + the structured fields, never from a free-form caller slot. The
agent can supply neither the template nor a free field, so there is no reachable
path by which model-generated prose becomes a note byte (the §6 grep-for-generated
-prose litmus has nothing to find — `tests/test_rewind.py` pins it).

Why a registry and not a bare enum
==================================

The same reason `reasons.py` is a registry: a closed set declared ONCE, as data,
that every consumer derives from. A `VerdictKind` value that is not in the active
registry is **not renderable** (`render` raises), so a note cannot carry a token
whose template the kernel did not author. `extend()` returns a NEW registry (you
compose, you don't mutate), so the closed-set property is a real value-level
guarantee, not a hope a plugin could scribble over mid-run. The three built-in
forms are exactly docs/164 §6's three: `DIVERGED`, `VERIFY_NOT_SHIPPED`,
`TOOL_STREAM_REPEATING`.

Pure stdlib — no third-party imports, no I/O, no `dos`-internal deps (a leaf, like
`reasons.py`) — so `rewind` can import it as a sibling kernel leaf.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping


@dataclass(frozen=True)
class VerdictTokenSpec:
    """One no-good token KIND, as data — the unit a workspace declares to add a form.

    The `ReasonSpec` analogue. Fields:

      kind     — the closed token identifier (canonical UPPER_SNAKE; the registry
                 normalizes case on lookup). The thing a `VerdictToken` references;
                 a token whose kind is not a member of the active registry is not
                 renderable, which is the structural lock.
      template — a `str.format_map`-style template OWNED BY THE KERNEL, rendered
                 over the token's structured `payload`. This is the only source of
                 the rendered prose — the caller supplies STRUCTURED FIELDS the
                 kernel computed (a sha, a count), never the sentence. An unknown
                 payload key is simply absent from the template; a template key the
                 payload omits renders as an empty placeholder (a defaulting map),
                 so a partial payload degrades to a still-kernel-authored string,
                 never a raise that would let an exception text leak.
      fields   — the payload keys this form expects (documentation + a `dos man`
                 projection; not enforced — an extra key is dropped, a missing key
                 blanks). Co-located with the kind by design (the DOM rule).
      summary  — one-line gloss of what the token MEANS (the man-page NAME line).
    """

    kind: str
    template: str
    fields: tuple[str, ...] = ()
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.kind or not self.kind.strip():
            raise ValueError("VerdictTokenSpec.kind must be a non-empty string")
        if not self.template or not self.template.strip():
            raise ValueError(
                f"VerdictTokenSpec {self.kind!r} must carry a non-empty render "
                f"template — the kernel-authored string the token renders to "
                f"(a token with no template would have no un-forged way to render)"
            )

    @property
    def key(self) -> str:
        """The normalized lookup key (UPPER, stripped) — what `get` matches."""
        return self.kind.strip().upper()


class _BlankingDict(dict):
    """A `format_map` backing dict that renders a missing key as an empty string.

    So a template key the payload omits blanks (kernel-authored, still un-forged)
    rather than raising a `KeyError` whose text could leak into a caller's except
    handler. The kernel's template is the author either way.
    """

    def __missing__(self, key: str) -> str:  # pragma: no cover - exercised via render
        return ""


@dataclass(frozen=True)
class VerdictToken:
    """One no-good annotation token: a `(kind, payload)` pair, NEVER a free string.

    This is the (a)-class byte of the docs/164 §6 no-good note. The agent cannot
    construct one that carries arbitrary prose: `kind` must resolve to a registry
    spec to render at all, and `payload` is a `{str: str}` map of STRUCTURED fields
    (a sha, a count, a turn index) that the kernel computed — fed into the
    registry-owned template. There is no `text`/`message`/`critique` field a caller
    fills freely. That absence is the lock the §6 grep-litmus relies on.

      kind    — the token identifier; must be a member of the registry that renders
                it (else `render` raises — an undeclared kind has no kernel template).
      payload — structured fields (all coerced to `str`), substituted into the
                registry's template. Extra keys are dropped by the template; missing
                keys blank. Never a sentence — a count, a sha, an index.
    """

    kind: str
    payload: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Coerce the payload to a plain, immutable-by-discipline str→str dict so a
        # caller cannot smuggle a non-string (a callable, a nested structure that a
        # template could `__str__` into prose) into a field slot.
        object.__setattr__(
            self,
            "payload",
            {str(k): str(v) for k, v in dict(self.payload).items()},
        )

    @property
    def key(self) -> str:
        return self.kind.strip().upper()


@dataclass(frozen=True)
class RewindTokenRegistry:
    """A closed, ordered set of `VerdictTokenSpec`s — the active no-good vocabulary.

    The `ReasonRegistry` analogue, immutable: `extend()` returns a NEW registry. A
    process's active registry is a value, never a mutable global a plugin scribbles
    on — which is what keeps "closed set" a real property. The kernel renders a
    `VerdictToken` ONLY through this registry's template for the token's kind, so a
    token whose kind is absent here is structurally unrenderable: there is no
    code path by which generated prose, lacking a registered kind + template, can
    become a rendered note byte.
    """

    specs: tuple[VerdictTokenSpec, ...] = ()

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for s in self.specs:
            if s.key in seen:
                raise ValueError(
                    f"duplicate token kind {s.kind!r} in registry — a no-good token "
                    f"kind is declared exactly once (a later declaration would shadow "
                    f"silently, the drift this registry exists to forbid)"
                )
            seen.add(s.key)

    # -- lookup ------------------------------------------------------------
    def get(self, kind: str | None) -> VerdictTokenSpec | None:
        """The spec for `kind`, or None if not a member of this set."""
        if not kind:
            return None
        k = kind.strip().upper()
        for s in self.specs:
            if s.key == k:
                return s
        return None

    def is_known(self, kind: str | None) -> bool:
        return self.get(kind) is not None

    def kinds(self) -> tuple[str, ...]:
        """Every declared kind, in declaration order."""
        return tuple(s.key for s in self.specs)

    # -- the render mechanism (the whole point) ---------------------------
    def render(self, token: VerdictToken) -> str:
        """Render `token` to its KERNEL-AUTHORED string. The only way a token becomes prose.

        The string is composed from THIS registry's template for the token's kind +
        the token's structured payload. The caller supplied neither — only the
        structured fields. A token whose kind is not a member of this registry has
        no kernel template, so it is NOT renderable: `render` raises `ValueError`.
        That raise is the structural lock — a generated critique, having no
        registered kind, can never reach a rendered note byte (the §6 litmus). A
        recognised kind with a partial payload blanks the missing fields
        (`_BlankingDict`) rather than raising, so a partial-but-honest token still
        renders a kernel-authored string.
        """
        spec = self.get(token.kind)
        if spec is None:
            raise ValueError(
                f"un-renderable no-good token kind {token.kind!r}: not a member of "
                f"the active RewindTokenRegistry (known: {', '.join(self.kinds()) or '∅'}). "
                f"A token the kernel has no template for cannot author un-forged note "
                f"bytes — this is the docs/164 §6 generated-prose lock, working."
            )
        return spec.template.format_map(_BlankingDict(token.payload))

    # -- composition (the hackability verb) -------------------------------
    def extend(self, more: Iterable[VerdictTokenSpec]) -> "RewindTokenRegistry":
        """Return a NEW registry with `more` appended. The one way to add forms.

        Raises on a colliding kind (the same declared-exactly-once guard
        `__post_init__` enforces) — a workspace re-declaring a built-in is a mistake
        to surface, not silently honor.
        """
        return RewindTokenRegistry(specs=tuple(self.specs) + tuple(more))


# ---------------------------------------------------------------------------
# The built-in registry — exactly docs/164 §6's three no-good forms. Each
# template is KERNEL-AUTHORED; the {placeholders} are the structured fields the
# kernel computed (a sha, a count, a turn index), never a caller-supplied
# sentence. A workspace adds a form via `BASE_REWIND_TOKENS.extend([...])`.
# ---------------------------------------------------------------------------

# The closed kind identifiers (string constants so a builder references them by
# name without re-typing the literal — the lockstep `wedge_reason` uses).
KIND_DIVERGED = "DIVERGED"
KIND_VERIFY_NOT_SHIPPED = "VERIFY_NOT_SHIPPED"
KIND_TOOL_STREAM_REPEATING = "TOOL_STREAM_REPEATING"

BASE_REWIND_TOKENS = RewindTokenRegistry(specs=(
    VerdictTokenSpec(
        kind=KIND_DIVERGED,
        template="resume = DIVERGED",
        fields=(),
        summary="ground truth moved past the resume point — the prior branch is a "
                "dead end (resume.Resume.DIVERGED).",
    ),
    VerdictTokenSpec(
        kind=KIND_VERIFY_NOT_SHIPPED,
        template="verify = NOT_SHIPPED @ {sha}",
        fields=("sha",),
        summary="the claimed phase did not actually ship at the named SHA "
                "(oracle.is_shipped → NOT_SHIPPED).",
    ),
    VerdictTokenSpec(
        kind=KIND_TOOL_STREAM_REPEATING,
        template="tool_stream = REPEATING ×{count} @ turn {turn}",
        fields=("count", "turn"),
        summary="the same (tool, args, result) recurred N times — the env's results "
                "stopped advancing (tool_stream.classify_stream → REPEATING).",
    ),
))

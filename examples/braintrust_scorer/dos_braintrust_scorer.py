"""`dos reward` as a Braintrust custom code scorer (issue #48).

The believe-the-agent point: Braintrust's scorer shelf grades TEXT — an LLM
judge or a string metric reads the agent's output and mints the score. Both
read bytes the agent authored, so a confidently-narrated failure scores like a
success (the docs/234 measurement: a narration-reading judge false-accepts
0.352; the deterministic world-read floor 0.000). Braintrust code scorers run
with egress — and an HTTP-endpoint scorer runs on your own infrastructure —
so unlike a network-sandboxed hosted evaluator, a scorer HERE can actually
reach the evidence.

This module is the drop: `dos.reward.admit` (docs/230/234) in Braintrust's
handler shape. The closed verdict maps onto the score like this:

    ACCEPT        -> score 1.0   (a non-forgeable witness confirmed the claim)
    REJECT_POISON -> score 0.0   (the witness REFUTED it — the row a text
                                  grader would have scored high)
    ABSTAIN       -> score None  (no accountable witness reached — "no
    NO_CLAIM      -> score None   opinion", NEVER a silent 0 or a free 1)

`None` is load-bearing: Braintrust treats a null score as unscored, which is
the only honest projection of an abstain — a 0 would punish an unwitnessed
row, a 1 would mint a positive without evidence. The verdict + reason ride
the score's `metadata` so a reviewer sees WHY.

The two host jobs stay injected, never parsed here (the docs/234 §3 split):

  * `claim_extractor(output) -> bool` — PRECISION, reads forgeable text, can
    only route a row toward NO_CLAIM — never to a false accept.
  * `witness(task, metadata) -> Sequence[EvidenceFacts]` — SOUNDNESS,
    re-reads the WORLD. The default is the RECORDED-READBACK witness: your
    runtime logs the env's own read-back (a provider ledger row, an OS exit
    code) into the span's metadata at run time, and the scorer replays it —
    which is what makes offline scoring deterministic and this demo runnable
    with no account. A live witness (re-GET the API, read the DB) drops into
    the same parameter.

The floor holds either way: an AGENT_AUTHORED read-back — the agent pasting
its own "receipt" into metadata — is structurally ignored by
`believe_under_floor`; only OS_RECORDED / THIRD_PARTY can set ACCEPT.

Run offline (needs only `pip install dos-kernel`):

    python examples/braintrust_scorer/dos_braintrust_scorer.py

Pinned by `tests/test_braintrust_scorer_example.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from dos.evidence import Accountability, EvidenceFacts
from dos.reward import admit

__all__ = [
    "make_braintrust_scorer",
    "recorded_readback_witness",
    "run_fixture_demo",
]

_SCORE_MAP: Mapping[str, float | None] = {
    "ACCEPT": 1.0,
    "REJECT_POISON": 0.0,
    "ABSTAIN": None,
    "NO_CLAIM": None,
}


def recorded_readback_witness(
    task: str, metadata: Mapping[str, Any] | None
) -> tuple[EvidenceFacts, ...]:
    """Rebuild the env read-back your runtime RECORDED into the span metadata.

    Expected shape (one dict under ``metadata["readback"]``)::

        {"source_name": "provider_ledger", "accountability": "THIRD_PARTY",
         "stance": "ATTESTED" | "REFUTED" | "NO_SIGNAL",
         "subject": "...", "detail": "..."}

    Absent or malformed -> no read-back -> the verdict ABSTAINS (never a
    fabricated accept or reject). The accountability string is part of the
    record on purpose: a runtime that logs the agent's own paste as the
    read-back must mark it AGENT_AUTHORED, and the floor then ignores it.
    """
    rb = (metadata or {}).get("readback")
    if not isinstance(rb, Mapping):
        return ()
    try:
        acc = Accountability(rb["accountability"])
        stance = str(rb["stance"])
        source = str(rb["source_name"])
    except (KeyError, ValueError):
        return ()
    subject = str(rb.get("subject") or task)
    detail = str(rb.get("detail") or "")
    if stance == "ATTESTED":
        return (EvidenceFacts.attest(source, acc, subject, detail=detail),)
    if stance == "REFUTED":
        return (EvidenceFacts.refute(source, acc, subject, detail=detail),)
    return (EvidenceFacts.no_signal(source, acc, subject, detail=detail),)


def make_braintrust_scorer(
    claim_extractor: Callable[[str], bool],
    witness: Callable[[str, Mapping[str, Any] | None], Sequence[EvidenceFacts]]
    = recorded_readback_witness,
    name: str = "dos_reward",
) -> Callable[..., dict]:
    """Build the Braintrust handler: ``(input, output, expected, metadata) -> Score``.

    The returned function is the plain shape Braintrust code scorers use —
    online scoring config, playground, and `Eval(scores=[...])` all accept it.
    It returns a Score-shaped dict: ``{"name", "score", "metadata"}``.
    """

    def handler(
        input: Any = None,
        output: Any = None,
        expected: Any = None,
        metadata: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict:
        text = "" if output is None else str(output)
        task = str((metadata or {}).get("task") or input or "")
        claim_present = bool(claim_extractor(text))
        readbacks = tuple(witness(task, metadata)) if claim_present else ()
        label = admit(claim_present, readbacks, narrated=text)
        return {
            "name": name,
            "score": _SCORE_MAP[label.verdict.value],
            "metadata": label.to_dict(),
        }

    return handler


# ---------------------------------------------------------------------------
# The recorded-run fixtures + the offline demo.
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "recorded_runs.json"


def _demo_claim_extractor(output: str) -> bool:
    # PRECISION is host policy — a deliberately simple confident-write
    # detector (your host has its own). Forgeable text in, so the worst it
    # can do is route a row to NO_CLAIM, never to a false accept.
    return "cancelled" in output.lower()


def run_fixture_demo() -> dict[str, dict]:
    """Score the recorded runs offline. Returns Score rows keyed by case."""
    scorer = make_braintrust_scorer(_demo_claim_extractor)
    rows = json.loads(FIXTURES.read_text(encoding="utf-8"))
    return {
        case: scorer(
            input=row.get("input"),
            output=row.get("output"),
            metadata=row.get("metadata"),
        )
        for case, row in rows.items()
    }


def main() -> int:
    rows = run_fixture_demo()
    print(f"{'case':<16} {'score':>6}  verdict")
    for case, row in rows.items():
        score = "None" if row["score"] is None else f"{row['score']:.1f}"
        md = row["metadata"]
        print(f"{case:<16} {score:>6}  {md['verdict']} — {md['reason']}")
    print("\nA text grader scores the forged row like the witnessed one — the"
          "\nwords are identical. The witnessed verdict pays only the row whose"
          "\neffect the world's own record confirms; the self-attested receipt"
          "\nis structurally ignored (AGENT_AUTHORED never reaches ACCEPT).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

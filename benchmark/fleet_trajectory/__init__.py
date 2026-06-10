"""The fleet-trajectory benchmark (docs/243).

Turns this repo's own Claude Code session corpus — a natively *concurrent*
multi-session fleet hammering one shared git tree — into a labeled benchmark for
the DOS trust substrate. Five labeling tracks, each ordered hardest-witness-first,
each with gold authored by a byte the judged session did NOT write:

    A  concurrent over-write detection   (fleet-of-one wall, inverted)
    B  mid-trajectory over-claim         (claim/witness split, in-trace)
    C  recovery-vs-collapse              (detect->fix, confound named)
    D  peer-B handoff                    (causal, cross-session)
    E  token-waste / loop pathology      (cheap, already-tooled)

This is SCRATCH/benchmark tooling — it operates *on* the corpus, never inside the
kernel (the dependency arrow is one-way: it `import dos`; nothing under `src/dos/`
imports it). It reads the corpus read-only and writes only labels + derived
features, never the raw narration (the docs/243 §4.4 privacy split).
"""

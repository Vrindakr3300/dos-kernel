"""witness_ladder — the benchmark whose independent variable is WITNESS STRENGTH.

docs/261. Every other DOS benchmark holds the witness fixed and varies something
else (fleet size, model tier, detector, dataset). This one sweeps the
`Accountability` rung of the available witness and measures how the kernel's
write-admission verdict (`dos.reward.admit`) changes — holding the claim and the
ground truth fixed.

The result is ONE monotone curve that carries both halves of the DOS story:
  * the rising arm = the VALUE (poison purged where a non-forgeable witness exists);
  * the flat ABSTAIN BAND at the floor = the GROWTH FRONTIER (the docs/204 §3
    presence-not-goal wall, quantified as a fraction of the distribution, and
    labelled with the witness that would convert it).

Consumer side: imports `dos.reward` / `dos.evidence` and CALLS them; never
re-encodes the belief rule. The kernel one-way arrow (nothing under `src/dos/`
imports `benchmark`) is untouched.
"""

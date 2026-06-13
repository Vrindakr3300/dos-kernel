"""The keep-gate HARNESS — the witness tree the candidate may not touch (#35 floor).

Everything a generated-kernel candidate must NOT be able to author lives here:
the reference implementation it is checked against, the test-vector minter that
mints inputs AFTER the candidate is frozen, and the env-timer that measures
latency. The host enforces that a candidate diff confined to the kernel-source
lane leaves this whole subtree byte-identical — a harness-touching candidate is
structurally unkeepable (see `gate.py` and `README.md`).

This is the concrete fix surface for issue #35: the keep-gate's witnesses are
gathered by running things that live in a tree the candidate could edit; the
floor is a tree check that refuses any candidate whose diff reaches the witness
tree, BEFORE any improvement is weighed.
"""

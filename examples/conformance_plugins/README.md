# Conformance-plugin examples — prove the seam safety laws in YOUR CI

Three minimal, installable plugin packages — one per seam kind — each wired
to the `dos.testing` conformance suite (docs/306, issue #61). They are the
copy-paste starting point for a real plugin author: the smallest package
that registers an occupant under the kernel's entry-point group AND proves,
in its own pytest run, that the occupant composes under the kernel's safety
laws.

| Package | Seam | Occupant | The law its tests prove |
|---|---|---|---|
| `judge_plugin/` | `dos.judges` | `EvidenceCountJudge` (`evidence-count`) | a failing judge can only ABSTAIN, never AGREE |
| `overlap_policy_plugin/` | `dos.overlap_policies` | `BasenameOverlapPolicy` (`basename`) | a scorer can only refuse-MORE — a lying admit cannot pass the floor or the arbiter |
| `notifier_plugin/` | `dos.notifiers` | `CollectingNotifier` (`collecting`) | a raising transport is a non-delivered result, never a crashed producer |

## Run the proof out of tree (the issue #61 done-condition)

Each package works from ANY checkout — copy one anywhere, then:

```bash
python -m venv .venv && . .venv/bin/activate   # (Windows: .venv\Scripts\activate)
pip install dos-kernel pytest                  # the kernel + a runner
pip install -e .                               # your plugin (registers the entry point)
pytest -q                                      # the conformance suite, in YOUR checkout
```

Every `test_conformance.py` here has the same three parts a real plugin's
should:

1. a `Test*` subclass of the seam's conformance class, overriding the one
   factory (`make_judge` / `make_policy` / `make_notifier`);
2. behavior tables / behavior pins for the occupant itself (the judge one
   uses `JudgeTester`);
3. a by-name discovery check (`resolve_judge("evidence-count")` …) proving
   the entry-point registration in `pyproject.toml` actually took.

The kernel repo pins these examples against rot in
`tests/test_conformance_plugin_examples.py` (by-path import — everything
except the entry-point check, which needs the `pip install -e .`).

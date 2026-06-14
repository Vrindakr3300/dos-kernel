"""iot_tier — the model-tier recoverability sweep.

Turns the model-agnostic weak-model gate (benchmark/enterpriseops/weak_model_gate.py) into a
sweep across a declared model-size ladder (frontier -> mid -> small -> iot), measuring where
DOS's recoverable-failure fraction PEAKS and where it COLLAPSES. A $0, replay-first, calibrated
simulation: the corpora are synthetic (calibrated to a declared, cited per-tier failure mix) but
the detectors folded over them are the REAL shipped kernel classifiers, via the REAL gate fold.

See README.md for the honesty contract and the falsifier.
"""

"""E-TAU2-WRITEADMIT — the out-of-loop write-admission gate over the tau2 task (docs/216).

The $0 core (`gate.py`) is pure and importable today; the live driver (`live_loop.py`)
is gated behind `GEMINI_API_KEY`. See `docs/216` for the full go/no-go and `docs/228` for
the live J=5 result.

TWO CONSUMERS over the SAME join (claim-extractor + `db_match` witness + `believe_under_floor`):
  * `gate.py`       — the COMMONS consumer: does a downstream peer INHERIT A's write? (docs/228)
  * `rlvr_admit.py` — the LAB consumer: may a fine-tune TRAIN on A's run? The non-distillable
                      RLVR reward-label fork — forks `gate.admit` at the last function only
                      (`admit_to_reward_set`); $0 acceptance-precision arm on the live rows
                      (docs/216 §5, docs/230: J=5 poison purged, ΔP +40 pp).
"""

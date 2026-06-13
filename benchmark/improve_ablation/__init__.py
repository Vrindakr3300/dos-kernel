"""The keep-gate ablation (docs/318, issue #21) — measure what the verdicts buy.

Three copies of the same self-improving recipe loop, one decision rule apart:
arm A honors `dos.improve.classify` over a refereed measure, arm B keeps what
its own in-sample estimate claims helped, arm C honors the gate on a single
noisy sample (the issue-#34 failure, occurring naturally). The committed
RESULTS.md is the evidence file issue #21's done-condition asks for.
"""

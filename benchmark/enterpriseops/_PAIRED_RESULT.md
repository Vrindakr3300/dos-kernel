# Paired live rewind A/B — EnterpriseOps-Gym ITSM (2026-06-05)

> ⚠ **THIS IS THE SMALL, CONTRADICTED RUN (run B).** A more-powered run (run A: 48
> tasks × 4 domains, mint 0.40) REFUTED the conversion thesis (rewind −3.4pp vs block,
> fired-run flip −3). This n=20 ITSM-only run landed favorably (below) but two
> opposite-sign results on a sub-5pp effect = noise-dominated; the larger run governs.
> Read this as one small contradicting draw, NOT a confirmation. See docs/172 §3.5
> (the governing refutation) and docs/175 §8 (the reconciliation).

properly-paired (one invocation, shared sample): 20 common tasks, gemini-2.5-flash, mint 0.30/seed 42

| arm | verifier% | success% |
|---|---|---|
| none | 35.9 | 10.0 |
| block | 32.1 | 5.0 |
| rewind | 38.3 | 15.0 |

rewind - none = +2.4pp verifier / +5.0pp success
rewind - block = +6.2pp verifier / +10.0pp success
block - none = -3.8pp verifier (append negative)

## Fired-rewind slice (4 tasks)

| task | none | block | rewind | rewinds |
|---|---|---|---|---|
| task_20251221_231733_401_66392a82_514cea3c | 0.00 | 0.00 | 0.50 | 4 |
| task_20251222_140957_029_c5ca08eb_3c4271f0 | 0.67 | 0.00 | 0.67 | 1 |
| task_20260113_031046_703_99ba2325_54f35603 | 0.75 | 0.75 | 1.00 | 3 |
| task_20260115_152733_296_46ca2862_55f848d3 | 0.40 | 0.40 | 0.60 | 2 |

flip: help=3 hurt=0 net=3 | on fired: none=45.4% block=28.7% rewind=69.2%

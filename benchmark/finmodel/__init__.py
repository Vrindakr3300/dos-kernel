"""E-FINMODEL-RECOMPUTE — the docs/277 §3/§6 experiment #2 rung, on a FrontierFinance-style
financial-model corpus.

FrontierFinance (arXiv 2604.05912, 2026; long-horizon Excel modeling, 18h-expert tasks) is
the cleanest non-code fit in docs/277: its OWN failure catalogue *is* the forgery class DOS
refutes, in the paper's own words —

  * "unsupported or fabricated values embedded within otherwise valid results, making errors
    difficult to detect without detailed inspection"  (the static-value masquerade);
  * "balance sheets were often balanced with implausible, fabricated values merely to satisfy
    the balancing criteria"  (gaming the checker — the ImpossibleBench shape, docs/216);
  * "replaced formulas with static values, producing models that appeared complete but could
    not be updated";
  * "~88 hidden rows with missing labels formatted in white font … concealing the workaround".

The non-forgeable-witness defeat is identical across all of them, and it is the one DOS
already ships: **grade the RECOMPUTED quantity, not the ASSERTED one.** A financial model is
a graph of cells; the agent AUTHORS the stored value of every cell (forgeable floor), but a
deterministic engine that RE-EVALUATES every formula from its precedents authors a value the
agent did not — the `OS_RECORDED` rung. The gate REFUTES any cell whose stored value ≠ its
recomputed value, and any balance achieved by a plug value with no precedent trace.

This package mirrors `benchmark/agentdiff/` exactly:

  model.py    — the financial-model artifact (a cell graph) + the deterministic recompute
                engine (the NON-FORGEABLE witness; the agent authors zero of its bytes).
  claim.py    — the CLAIM side (FORGEABLE): a model's stored values + its asserted balance,
                i.e. what the agent took credit for ("the model is complete and balances").
  gate.py     — the recompute witness JOIN over the shipped `dos.effect_witness`: BLOCK iff a
                completion-claim is REFUTED by the recompute witness; ADMIT otherwise.
  dataset.py  — the labeled $0 corpus: clean human-built models + deterministically-injected
                static-value-masquerade, fabricated-balance, and plug-balance forgeries.

DISCIPLINE (the Tier line). This verifies MECHANICAL SOUNDNESS — the layer the paper says
distinguishes human experts ("correctly linked," "auditable"). It does NOT make the financial
JUDGMENT right (is this the right discount rate / projection — Tier 3, abstain). A J here is a
caught-forgery count, never a better model.
"""

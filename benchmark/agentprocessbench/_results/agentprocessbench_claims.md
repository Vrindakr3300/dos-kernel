# AgentProcessBench boundary + error-slice-floor claims (docs/174, SSOT)

Corpus: AgentProcessBench (RUCBM, arXiv 2603.14465, MIT), scored offline, $0.
Contrast anchor: LLM-judge best FirstErrAcc = 65.8% (Gemini-3-Flash-Thinking).

The gold rates task EFFECTIVENESS, not tool errors. The byte-clean detector reads only the
env-authored tool-status channel, so its FirstErrAcc ceiling is the ERROR-CAUSED fraction.
This is a BOUNDARY + a deterministic FLOOR, NOT a judge rival.

## bfcl (structured — the method's home)
- trajectories: 250 (184 with a gold first-divergence)
- BOUNDARY — error-caused first-divergences: 20/184 = 10.9% (so 89.1% are SILENT — no error byte, out of byte-clean reach)
- ERROR-SLICE FLOOR — first_env_error FirstErrAcc on the error-caused slice: 19/20 = 95.0% (false-alarm 25/62 = 40.3%)
- recovery-gated variant (first_unrecovered_env_error): slice FirstErrAcc 2/20 = 10.0%, false-alarm 1/62 = 1.6% — cuts false-alarm but on bfcl over-suppresses errored-then-still-wrong divergences
- byte-clean CEILING (FirstErrAcc over ALL localizable): 19/184 = 10.3% (vs judge 65.8%)

## tau2 (structured — the method's home)
- trajectories: 250 (143 with a gold first-divergence)
- BOUNDARY — error-caused first-divergences: 39/143 = 27.3% (so 72.7% are SILENT — no error byte, out of byte-clean reach)
- ERROR-SLICE FLOOR — first_env_error FirstErrAcc on the error-caused slice: 39/39 = 100.0% (false-alarm 6/103 = 5.8%)
- recovery-gated variant (first_unrecovered_env_error): slice FirstErrAcc 25/39 = 64.1%, false-alarm 2/103 = 1.9% — cuts false-alarm but on bfcl over-suppresses errored-then-still-wrong divergences
- byte-clean CEILING (FirstErrAcc over ALL localizable): 39/143 = 27.3% (vs judge 65.8%)

## gaia_dev (free-text — degrades)
- trajectories: 250 (183 with a gold first-divergence)
- BOUNDARY — error-caused first-divergences: 0/183 = 0.0% (so 100.0% are SILENT — no error byte, out of byte-clean reach)
- ERROR-SLICE FLOOR — first_env_error FirstErrAcc on the error-caused slice: 0/0 = 0.0% (false-alarm 0/67 = 0.0%)
- recovery-gated variant (first_unrecovered_env_error): slice FirstErrAcc 0/0 = 0.0%, false-alarm 0/67 = 0.0% — cuts false-alarm but on bfcl over-suppresses errored-then-still-wrong divergences
- byte-clean CEILING (FirstErrAcc over ALL localizable): 0/183 = 0.0% (vs judge 65.8%)

## hotpotqa (free-text — degrades)
- trajectories: 250 (104 with a gold first-divergence)
- BOUNDARY — error-caused first-divergences: 1/104 = 1.0% (so 99.0% are SILENT — no error byte, out of byte-clean reach)
- ERROR-SLICE FLOOR — first_env_error FirstErrAcc on the error-caused slice: 1/1 = 100.0% (false-alarm 1/146 = 0.7%)
- recovery-gated variant (first_unrecovered_env_error): slice FirstErrAcc 0/1 = 0.0%, false-alarm 0/146 = 0.0% — cuts false-alarm but on bfcl over-suppresses errored-then-still-wrong divergences
- byte-clean CEILING (FirstErrAcc over ALL localizable): 1/104 = 1.0% (vs judge 65.8%)

## Headline (structured subsets bfcl+tau2)
- 59/327 = 18.0% of gold first-divergences are error-caused; the rest are SILENT semantic failures.
- That silent majority is the measured BOUNDARY where the deterministic ORACLE rung ends and the JUDGE/provenance rung must take over (docs/162 'errored != wrong', generalized).

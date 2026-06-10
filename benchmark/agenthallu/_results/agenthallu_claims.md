# AgentHallu Tool-Use step-localization claims (docs/166 §4, SSOT)

Corpus: AgentHallu (arXiv 2601.06818, CC-BY-4.0), scored offline, $0.
Comparison anchor: best frontier model on Tool-Use = 11.6% (Gemini-2.5-Pro).

## first_errored_response
- Tool-Use trajectories: 103
- EXACT gold-step hit: 35/103 = 34.0% (lift vs SOTA 11.6%: +22.4%, ~2.9x)
- within +/-1 step: 37/103 = 35.9%
- precision when fired: 35/72 = 48.6%
- FALSE-ALARM floor (clean trajectories): 88/250 = 35.2%

## first_structural_error
- Tool-Use trajectories: 103
- EXACT gold-step hit: 34/103 = 33.0% (lift vs SOTA 11.6%: +21.4%, ~2.8x)
- within +/-1 step: 36/103 = 35.0%
- precision when fired: 34/69 = 49.3%
- FALSE-ALARM floor (clean trajectories): 28/250 = 11.2%

## first_unrecovered_error
- Tool-Use trajectories: 103
- EXACT gold-step hit: 31/103 = 30.1% (lift vs SOTA 11.6%: +18.5%, ~2.6x)
- within +/-1 step: 32/103 = 31.1%
- precision when fired: 31/37 = 83.8%
- FALSE-ALARM floor (clean trajectories): 3/250 = 1.2%

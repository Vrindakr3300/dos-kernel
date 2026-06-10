```
# DOS detector vs trained-classifier baseline (docs/160)
# corpus: 6862 labeled rows · base fail rate 76.2% · 5-fold CV · thresholds dep=0.99/f1=0.03/rm=0.97
# lift = precision - base (skill above guessing); falarm = fires on a PASS

terminal_error                                 fire=  1.2%  prec= 95.0%  lift= 18.8%  recall=  1.5%  falarm=  0.2%  [tp/fp=76/4]
dangling_intent                                fire=  1.5%  prec= 98.0%  lift= 21.9%  recall=  1.9%  falarm=  0.1%  [tp/fp=100/2]
tool_stream                                    fire=  2.5%  prec= 88.2%  lift= 12.0%  recall=  2.9%  falarm=  1.2%  [tp/fp=150/20]
DOS trio (union)                               fire=  5.1%  prec= 92.6%  lift= 16.4%  recall=  6.2%  falarm=  1.6%  [tp/fp=323/26]
trained clf — DEPLOYABLE pt (5-fold held-out)  fire=  0.0%  prec=100.0%  lift= 23.8%  recall=  0.0%  falarm=  0.0%  [tp/fp=1/0]
trained clf — F1-OPTIMAL pt (5-fold held-out)  fire=100.0%  prec= 76.2%  lift=  0.0%  recall=100.0%  falarm= 99.9%  [tp/fp=5228/1632]
trained clf — recall-MATCHED to terminal_error fire=  1.5%  prec= 98.1%  lift= 21.9%  recall=  1.9%  falarm=  0.1%  [tp/fp=101/2]
trained clf — IN-SAMPLE @F1 (no split, OPTIMISTIC) fire=100.0%  prec= 76.2%  lift=  0.0%  recall=100.0%  falarm= 99.9%  [tp/fp=5228/1632]

# REGIME CAVEAT (the load-bearing point — docs/160 §1):
#   DOS detectors      : ZERO training, ZERO labels, one pass per trace, byte-clean,
#                        runs on a brand-new task with no prior data.
#   trained classifier : REQUIRES a labeled training corpus + a held-out split to be
#                        meaningful; the in-sample row shows how optimistic it looks
#                        WITHOUT the split. On a new domain with no labels it cannot
#                        run at all. Reads agent-authored structure -> mirror-verifier
#                        risk (degrades when the model trains against it).
#   => Not a replacement for the detector — a JUDGE-rung driver that would sit UNDER
#      the deterministic floor (ORACLE -> JUDGE -> HUMAN).
```

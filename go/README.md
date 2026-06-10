# `dos-hook` — the native hook fast-path (docs/125 GHF)

The first Go in the dos repo. One reason for it: the plugin's `hooks.json` fires
`python -m dos.cli hook …` on **every tool call**, paying ~0.3–0.8 s of Python
interpreter cold-start each time (measured 2026-06-08). A static Go binary erases
that — the decision a Claude Code operator *feels* on every call drops from
~600 ms to ~10 ms (~60×), with **byte-identical** output on the gated decision
projection (the [docs/124](../docs/124_the-go-core-build-plan-and-the-parity-contract.md)
parity contract).

This is a **wedge into** [100](../docs/100_native-spine-port-plan.md)/124, not a
fork: GHF5 folds these deciders into the NSP envelope ABI so there is one Go core,
not a hook silo beside an NSP silo.

## The boundary (unchanged from 100/124)

`dos-hook` is a **pure decider**. The CLI shell (`cmd/dos-hook`) gathers evidence
at the boundary — the live leases (folded from the lane-journal WAL) and the
runtime files that exist under the served workspace — and hands them to the pure
verdict in `internal/hook`. No verdict reads the disk, git, or the clock; all I/O
is at the edge, exactly the rule the Python kernel follows.

What it ports (the PRE-moment decider, `dos.pretool_sensor.decide` + its kernel
leaves):

| Go file | Ports |
|---|---|
| `tree.go` | `dos._tree` — the prefix algebra (`norm_tree_prefix`, `prefixes_collide`). |
| `overlap.go` | `dos.lane_overlap` — the disjointness scorer + the ⅓ ratio + exact-glob floor. |
| `selfmodify.go` | `dos.self_modify` — the runtime-file set + the self-modify collision. |
| `admission.go` | `dos.admission.run_predicates` — the [Disjointness, SelfModify] conjunction, empty-lease sentinel, empty-tree asymmetry. |
| `event.go` | `dos.pretool_sensor` PURE adapters — `is_pre_event`, `_tree_from_event`, the Bash path scrape, repo-relativize. |
| `dialect.go` | `deny_payload` / `warn_payload` — the exact CC PreToolUse dialect. |
| `pyjson.go` | `json.dumps(obj, sort_keys=True)` byte-for-byte (ensure_ascii, no slash/HTML escape, `", "`/`": "` separators). |
| `pyrepr.go` | Python `repr()` of a string (the `{lane!r}` in reason prose). |
| `fmtpct.go` | Python `f"{x:.0%}"` (round-half-to-even — agrees cross-engine, docs/124 §1.1). |
| `wal.go` | `dos.lane_journal.read_all`/`replay` (the live-lease fold) + the runtime-file existence probe. |
| `workspace.go` | the `SubstrateConfig` workspace + lane-journal-path resolution (env › `.dos/` default). |
| `decide.go` | the composed two-rung pretool decision, default `observe` handler → passthrough. |
| `journal_write.go` | `cli._journal_pretool_outcome` + `lane_journal.enforce_entry`/`append` — the OP_ENFORCE WAL write a native deny/warn does. |
| `posttool.go` | `posttool_sensor` + `tool_stream.classify_stream` — the SHA-256 digest, `step_from_event`, the REPEATING/STALLED fold, the WARN dialect, and the schema-tagged per-session stream accumulator (read+write). |

## Behavior + the fallback discipline

The binary self-dispatches with the fallback at the **shell**, not inside Go:

- `DOS_HOOK_NATIVE=1`, `pretool`, a **passthrough** → emit nothing, **exit 0**
  (the felt-latency win; the `||` does not run Python).
- a **deny/warn** → **exit 3** (DELEGATE) → the `hooks.json`
  `dos-hook … || python -m dos.cli hook …` runs the Python verb, which re-decides
  identically *and* writes the durable `OP_ENFORCE` journal record (GHF2 ports the
  WAL append so denies go native too).
- `posttool` (GHF2) → native: reads+appends the per-session stream
  (`.dos/streams/<sid>.jsonl`), classifies the trailing run, emits the
  REPEATING/STALLED WARN `additionalContext` (or nothing). It can never block
  (PostToolUse fires after the tool ran), so it always exits 0.
- `stop` → exit 3 (DELEGATE). Deliberately Python-delegated: it fires once per
  TURN (negligible cold-start) and its `verify()` rung hits the docs/124 §1.2 RE2
  lookbehind blocker (`phase_shipped`/`stamp` use lookbehind). Native `stop` is
  GHF5/124 scope (the oracle-cluster port).
- `DOS_HOOK_NATIVE` unset/0 → exit 3 (DELEGATE everything — today's Python
  behavior, byte-for-byte).
- **binary missing** → the shell `||` sees exit 127 and runs Python. No machine is
  blocked by a missing accelerator.
- a panic → recovered to **exit 0, nothing emitted** (a Go crash can never break a
  turn; the hook fail-safe wraps everything).

DOS denies via the JSON `permissionDecision: deny` dialect on stdout at exit 0 (the
CC contract) — **never** via a process exit code. Exit 3 is a delegate sentinel, not
a deny.

## Build & test

```bash
cd go
go build -o dos-hook ./cmd/dos-hook      # or dos-hook.exe on Windows
go test ./internal/hook/                  # unit + pyjson + the parity corpus
```

## The differential parity gate (GHF3)

The byte-exact contract is enforced by a cross-engine differential:

```bash
# regenerate the hermetic corpus from the LIVE Python decider:
python internal/hook/parity/gen_corpus.py > internal/hook/parity/corpus.jsonl
# the Go test replays each case and asserts byte-equality:
go test ./internal/hook/ -run TestParityCorpus
```

`tests/test_go_hook_parity.py` (in the repo root suite) is the CI ratchet: it
regenerates the corpus, asserts it is self-consistent with the committed one, and
runs `go test` (skipping cleanly when Go is absent). A decision drift fails loudly;
a reason-prose-only difference is carried, not gated (docs/124 §2) — though the
hook's reason is pure int/enum/path prose, so today the whole emitted line matches.

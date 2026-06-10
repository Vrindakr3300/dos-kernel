# 225 — The notification spine: a `Notifier` seam, and Slack as its first driver

> **The verdict is the kernel; *where it lands* is a driver.** DOS already has two
> read-only projections of "what needs a human" (`dos decisions`) and "what is
> running now" (`dos top`). Today both render only to the operator's *own*
> terminal. A fleet runs unattended; the operator is in Slack. The notification
> spine is the seam that pushes those two projections *out* — to Slack first, to
> PagerDuty / email / a webhook later — **without the kernel ever naming a
> transport.**

## The shape (decided)

This is the kernel's pure-protocol + by-name-resolver pattern, for the **fourth**
time, now on the *delivery* side:

| Instance | Seam (kernel) | Drivers (named) | Failure direction |
|---|---|---|---|
| `dos.judges` | `Judge` protocol + `AbstainJudge` | `llm` / `similarity` / … | fail-to-**abstain** |
| `dos.overlap_policy` | scorer protocol + `prefix` floor | model scorers | fail-to-**floor** (refuse-more) |
| `dos.hook_dialect` | neutral verdict + `claude-code` | `gemini` / `codex` / `cursor` | fail-**LOUD** (wrong dialect = no-op) |
| **`dos.notify` (this)** | **`Notifier` protocol + `null` sink** | **`slack`** / pagerduty / webhook | fail-**SOFT** (a dropped notification never breaks the run) |

The user picked the **generic seam + Slack driver**, surfacing **both** a
decisions digest (a Block Kit *post*) and a live fleet status (an *edit-in-place*
message). Both are built.

### Why a seam, not just a Slack module

The same reason `hook_dialect` is a seam and not a `print_cc()`: the moment a
*second* transport is plausible (PagerDuty for the LIVENESS-halt page, a webhook
for a dashboard), a hard-coded Slack call is the thing you have to tear out. A
`Notifier` protocol means a new transport is a driver + one entry-point line,
never a kernel edit — the litmus the whole package is built around.

### Why `slack_helpers` lives behind an extra

Exactly the `[mcp]` / `[tui]` precedent: the kernel's dependency set stays
PyYAML-only. `slack_helpers` (which pulls `requests`) is pinned only by a new
`[notify-slack]` extra. `pip install dos-kernel` is unchanged;
`pip install dos-kernel[notify-slack]` adds the transport. The Slack driver
imports `slack_helpers` **lazily** and fails with an install hint if the extra is
absent — the `dos_mcp` discipline.

---

## Layer 1 — the kernel seam: `src/dos/notify.py`

Pure stdlib, no I/O, no transport name. Mirrors `judges.py` / `hook_dialect.py`.

### The neutral payload — `Notification`

A transport-agnostic value the *renderers* (layer 1) produce and the *drivers*
(layer 4) consume. It is NOT Slack Block Kit (that is Slack's shape) — it is the
DOS-shaped fact:

```python
class Severity(str, enum.Enum):      # str-valued → round-trips through --json
    INFO = "INFO"        # a status digest, nothing wrong
    WARN = "WARN"        # a refusal / wedge is pending
    URGENT = "URGENT"    # a LIVENESS halt — a run is spinning/hung NOW

@dataclass(frozen=True)
class Notification:
    severity: Severity
    title: str                      # the one-line headline ("3 decisions need you")
    summary: str                    # the plain-text body (reuses the existing renderers)
    fields: tuple[tuple[str, str], ...] = ()   # (label, value) pairs → Block Kit fields / k=v lines
    key: str = ""                   # a stable identity for edit-in-place (the live-status case)
    source: str = ""                # "decisions" | "top" — which projection this came from
    def to_dict(self) -> dict: ...
```

`key` is the load-bearing field for the live-status surface: a notifier that
supports editing (Slack via `LiveMessage`) keys its single re-edited message on
`key` (e.g. `"dos-top:<workspace>"`), so a status stream updates ONE message
instead of spamming the channel. A notifier that cannot edit ignores `key` and
posts.

### The pure renderers — projection → `Notification`

The kernel already has the hard part: `decisions.collect_decisions()` and
`dispatch_top.snapshot()` return typed, `to_dict()`-able data, and
`decisions.render_list_plain()` / `dispatch_top.render_frame_text()` produce the
plain-text body. The seam adds two **pure** adapters (data in, `Notification`
out — no I/O, unit-test surface, the `picker_oracle.classify` posture):

- `notification_for_decisions(rows: list[Decision]) -> Notification`
  - `severity` = URGENT if any LIVENESS row, else WARN if any row, else INFO.
  - `title` = `"<n> decisions need you"` (or `"fleet clear — no pending decisions"`).
  - `summary` = `decisions.render_list_plain(rows)` (reuse — one renderer, no drift).
  - `fields` = the top-K rows as `(kind/lane, reason)` pairs (the **TOP** decisions
    the user asked to surface — ranked by the existing `_KIND_RANK`, so a LIVENESS
    halt is field #1).
  - `key` = `"dos-decisions:<workspace>"`, `source = "decisions"`.
- `notification_for_top(frame: Frame) -> Notification`
  - `severity` = URGENT if any lane STALLED, WARN if any SPINNING, else INFO.
  - `title` = `"fleet: <a> advancing · <s> spinning · <x> stalled · <f> free"`.
  - `summary` = `dispatch_top.render_frame_text(frame)`.
  - `fields` = per-non-free-lane `(lane, chip + holder)` + a "recent verdicts" tally.
  - `key` = `"dos-top:<workspace>"`, `source = "top"`.

> **Boundary discipline (the one wrinkle).** `notify.py` importing `decisions` /
> `dispatch_top` would make a kernel module import two *helper-layer* (layer-3)
> modules — backwards on the dependency arrow. So the two adapters take the
> **already-built** `list[Decision]` / `Frame` as arguments (pure over data); the
> CLI verb (layer 3) is what calls `collect_decisions()` / `snapshot()` and hands
> the result in. `notify.py` imports only `Decision` / `Frame` as *types* (or, to
> stay even cleaner, duck-types them via the fields it reads). This keeps
> `notify.py` a true layer-1 leaf. **(Confirm during build: type-only import vs.
> duck-type — lean duck-type if the `TYPE_CHECKING` import reads awkwardly.)**

### The `Notifier` protocol + resolver + built-in null sink

```python
@runtime_checkable
class Notifier(Protocol):
    def send(self, note: Notification) -> NotifyResult: ...   # deliver (post or edit-in-place)

@dataclass(frozen=True)
class NotifyResult:
    delivered: bool
    detail: str = ""        # "posted ts=… " / "edited" / "dry-run" / "no token — skipped"
    ref: str = ""           # the transport's message id (Slack ts), for a later edit

class NullNotifier:         # the unshadowable built-in — the honest zero
    name = "null"
    def send(self, note): return NotifyResult(delivered=False, detail="null sink")
```

- `resolve_notifier(name) -> Notifier` — built-ins first (`null`), then the
  `dos.notifiers` entry-point group (the `resolve_judge` / `resolve_dialect`
  shape). `active_notifiers()` discovers all; discovery I/O at the call boundary.
- **Failure direction = fail-SOFT.** Unlike `hook_dialect` (fail-loud), a
  notification is advisory telemetry — a transport that raises or is mis-wired
  must **never** crash the fleet loop that emitted it. So `send_safely(notifier,
  note)` wraps `send` and converts any raise to `NotifyResult(delivered=False,
  detail="error: …")`. A *resolve* of an unknown name still raises (operator
  error, surfaced at config time, like `dos.judges`), but a *send* never does.
  This is the `LiveMessage._warn` philosophy lifted to the seam: "a streaming UI
  never crashes its producer."

> **The advisory floor (docs/99).** The notifier REPORTS; it never *acts on* the
> fleet. It cannot acquire a lease, stop a run, or mutate state — it is a pure
> read-of-a-projection → push. A LIVENESS-halt notification *describes* a proposed
> stop and carries the paste-to-stop command in a field; enacting it stays the
> operator's call. This is `decisions.py`'s locked read-only-router model,
> extended across the network boundary.

---

## Layer 4 — the driver: `src/dos/drivers/notify_slack.py`

Where the transport name is allowed to be code (a `SlackNotifier` is inherently
Slack-specific — the `GeminiDialect` rule). Registered:

```toml
[project.entry-points."dos.notifiers"]
slack = "dos.drivers.notify_slack:SlackNotifier"
```

```python
class SlackNotifier:
    name = "slack"
    def __init__(self, *, channel, token=None, dry_run=False, edit_in_place=None, client=None):
        # token: SLACK_BOT_TOKEN (arg › env › workspace .env).  client: inject a fake in tests.
        # edit_in_place: None = auto (INFO/status edits, WARN/URGENT post); True/False force.
    def send(self, note) -> NotifyResult: ...
```

Mapping `Notification` → Slack:
- **Block Kit body** from `note` — a `header` (title, severity emoji 🟢/🟡/🔴), a
  `section` of `fields` (the TOP rows / lane chips), and the `summary` in a
  fenced code block. A small local builder (the spine's *DOS-shaped* analogue of
  `slack_helpers.build_upload_blocks`); the seam stays Block-Kit-free.
- **Post vs. edit-in-place** — the two surfaces the user picked:
  - *Decisions digest* → `client.post_message(channel, title, blocks)` (a fresh
    post each run; cron/event-driven). Returns `ref = ts`.
  - *Live fleet status* → a process-lived `LiveMessage(client, channel,
    min_interval=…)` keyed on `note.key`: the first `send` posts, later sends with
    the same `key` call `.update(summary)` → ONE edited message. This is the exact
    `LiveMessage` use-case ("emit a running log into ONE Slack message rather than
    spamming the channel"). Maps the kernel `key` onto the transport's edit handle.
- **Token / channel resolution** — `SLACK_BOT_TOKEN` from arg › env › the
  workspace `.env` (the `slack_helpers` convention); channel from `--channel`
  (a name resolved through `slack_config.json`, or a raw `C0…` id). No token →
  `NotifyResult(delivered=False, detail="no SLACK_BOT_TOKEN — skipped")`, never a
  crash (fail-soft).
- **`slack_helpers` imported lazily** inside `send` / `__init__`; absent extra →
  a `NotifyResult` with an install hint, not an `ImportError` at module load.

---

## Layer 3 — the CLI verb: `dos notify`

A thin shell over the seam (the `cmd_decisions` / `cmd_top` posture — wire only,
no policy):

```
dos notify decisions [--notifier slack] [--channel NAME] [--top K] [--all] [--dry-run] [--json]
dos notify top        [--notifier slack] [--channel NAME] [--dry-run] [--json]
```

- `cmd_notify` calls the *existing* readers (`decisions.collect_decisions(cfg,
  resolver=…)` / `dispatch_top.snapshot(cfg)`), pipes the result through the pure
  adapter (`notification_for_decisions` / `_for_top`), resolves the notifier
  (`--notifier`, default **`null`** — so a bare `dos notify` is a safe no-op that
  prints the payload), and `send_safely`s it.
- `--dry-run` → resolve + render + print the `Notification.to_dict()` and the
  Slack `[dry-run]` line, send nothing (the `slack_helpers` `--dry-run`
  convention, and the kernel-dogfood "read the verdict before you act" move).
- `--json` → print the `Notification` + the `NotifyResult` as JSON (the
  machine-readable surface every other verb has).
- **Default notifier is `null`, default mode is dry-ish**: pushing to an external
  service is outward-facing, so the verb prints-by-default and only sends when a
  real `--notifier` + channel are named. (The "confirm before outward-facing"
  rule, encoded as a default.)

### Recurring delivery is NOT in the kernel

A fleet wants this *pushed on a cadence* ("every 5 min, or on a new LIVENESS
halt"). That cadence is **host concern**, exactly like the dispatch loop: the
kernel ships the one-shot `dos notify`, and the operator drives it with the
harness `/loop` skill (`/loop 5m dos notify top --notifier slack --channel ops`)
or a cron / a `dos.notifiers`-aware supervisor. No scheduler, no daemon, no state
inside `notify.py` — the same line `dos top --once` draws against the `[tui]` poll
loop. (A future `drivers/notify_supervisor.py` could fold "only page on a *new*
URGENT, debounce the rest" — the `LiveMessage` throttle is already the per-message
half of that.)

---

## Litmus tests this must pass (the contract, enforced)

1. **Kernel names no transport.** `notify.py` contains no `"slack"`, no
   `import slack_helpers`, no `requests`, no Block Kit. Grep-checkable; the
   `SlackNotifier` is the only place "slack" appears as code, in a driver. (The
   `hook_dialect` vendor-blindness litmus, restated for delivery.)
2. **Kernel imports no driver.** No `from dos.drivers` in `notify.py`; the Slack
   notifier is discovered by name. (The `dos.judges` rule.)
3. **`notify.py` is a true leaf.** It imports no layer-3 module
   (`decisions`/`dispatch_top`) at runtime — the adapters are pure over the
   passed-in `Decision`/`Frame` data. (The dependency-arrow rule.)
4. **A send never crashes the producer.** `send_safely` converts any driver raise
   to a non-delivered result. Pinned by a test with a raising fake notifier.
5. **No token / no extra → graceful skip, not a crash.** `SlackNotifier` with no
   token and with `slack_helpers` absent both return a `NotifyResult`, never throw.
6. **`dry_run` sends nothing.** A fake `SlackClient` asserts zero `post_message` /
   `update_message` calls under `--dry-run`.
7. **The default is a no-op.** `dos notify decisions` with no `--notifier`
   resolves `null`, prints, sends nothing — safe by construction.
8. **The core install is unchanged.** `pip install dos-kernel` pulls no new dep;
   `slack_helpers` is only in `[notify-slack]`. (The `[mcp]`/`[tui]` precedent.)

---

## Files

| Path | Layer | What |
|---|---|---|
| `src/dos/notify.py` | 1 (kernel) | `Severity`/`Notification`/`Notifier`/`NotifyResult`/`NullNotifier`, the two pure adapters, `resolve_notifier`/`active_notifiers`/`send_safely` |
| `src/dos/drivers/notify_slack.py` | 4 (driver) | `SlackNotifier` — Block Kit builder, post + `LiveMessage` edit-in-place, token/channel resolution, lazy `slack_helpers` import |
| `src/dos/cli.py` | 3 (helper) | `cmd_notify` + the `dos notify {decisions,top}` subparsers |
| `pyproject.toml` | — | `[project.entry-points."dos.notifiers"] slack = …` + `[project.optional-dependencies] notify-slack = ["slack-helpers>=0.2"]` |
| `tests/test_notify.py` | — | the seam: adapters, resolver, `send_safely`, null sink (pure, no network) |
| `tests/test_notify_slack.py` | — | the driver, against a **fake** `SlackClient` (post/edit/dry-run/no-token/absent-extra) |
| `CLAUDE.md`, `docs/README.md` | — | the new seam row in the layering table + the syscall/driver note |

## Build order

1. `notify.py` (seam + adapters + null sink + resolver + `send_safely`) and
   `test_notify.py` — pure, no network, lands green on its own.
2. `notify_slack.py` (against a fake client) + `test_notify_slack.py` — driver,
   still no real network.
3. `pyproject.toml` entry-point + extra; `pip install -e .` so the driver is
   discoverable by name.
4. `dos notify` CLI wiring.
5. **Manual dogfood** (the kernel-on-kernel ritual): `dos notify decisions
   --dry-run` then, with `pip install -e slack-helpers/` + the token in
   a local `.env`, a real `dos notify top --notifier slack --channel <test>` to a
   throwaway channel.
6. CLAUDE.md / docs/README.md layering-table row; commit (scoped pathspec).

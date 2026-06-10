# 267 — The webhook notifier: the universal transport on the `dos.notifiers` seam

> **The seam shipped with one transport; its own docstring names the gap.**
> `notify.py` (docs/225) is the transport-agnostic notification spine — `Notification`
> + the `Notifier` Protocol + `send_safely` + the `null` built-in + the `dos.notifiers`
> resolver — and it ships exactly one driver: Slack. The module docstring itself says
> *"PagerDuty / email / a webhook are later drivers."* This plan builds the **webhook**
> driver, and it is deliberately the first of the three because **a generic HTTP POST
> is the universal transport**: Microsoft Teams, Discord, PagerDuty Events API, Opsgenie,
> a Zapier/n8n hook, an internal incident bus, and a homegrown endpoint are all "POST
> this JSON to this URL." One stdlib driver turns the notification spine from
> Slack-only into "reaches anything that accepts a webhook," with **no new dependency**.

*Status: design + the build target of this work. The seam (`dos.notify`) and the
`dos.notifiers` group are SHIPPED; this adds one driver + one entry-point + tests. It
is the cheapest of the three outward-connector gaps (docs/265/266 are the other two).*

## 0. Why webhook, and why first

The notification spine has a `Notifier` for "what needs a human" / "what's running" but
can only deliver to Slack. The three named-but-unbuilt transports are PagerDuty, email,
and a webhook — and a webhook **subsumes most of the other two and far more**:

- **Teams / Discord / Mattermost / Zulip** — all accept an incoming-webhook URL and a
  JSON body. A DOS webhook notifier reaches every chat platform Slack-style, not just
  Slack.
- **PagerDuty / Opsgenie / incident.io** — their event-ingest APIs are "POST JSON to a
  URL with a routing key." A webhook notifier with a configurable URL + header is the
  PagerDuty driver, minus the vendor-specific payload polish (a thin PagerDuty driver
  can come later as a payload-shaping subclass).
- **Automation (Zapier / n8n / Make / a Lambda Function URL)** — the universal "do
  anything with this event" adapter is a webhook. Email-via-webhook (SendGrid/Postmark
  inbound) falls out of this for free.

So the webhook driver is the **highest-leverage single transport**, and it costs the
least: the entire seam (payload, protocol, resolver, fail-soft wrapper, the `null`
baseline) already ships and is tested against Slack — the webhook driver is one new
`drivers/notify_webhook.py` that mirrors `notify_slack.py`, one `pyproject` line, and a
test file that mirrors `test_notify_slack.py`. And unlike Slack (which pulls
`slack_helpers` → `requests` in the `[notify-slack]` extra), a webhook needs only
`urllib.request` from the standard library — **zero new dependency, ships in the core.**

## 1. The driver — `dos.drivers.notify_webhook.WebhookNotifier`

Mirrors `SlackNotifier` field-for-field, because the seam already dictates the shape (a
class with `name`, a constructor, a fail-soft `send(note) -> NotifyResult`).

```python
class WebhookNotifier:
    name = "webhook"
    def __init__(self, *, url: str = "", token: str | None = None,
                 root: PathLike | str | None = None, dry_run: bool = False,
                 method: str = "POST", headers: dict | None = None,
                 timeout: float = 10.0, transport=None):
        ...
    def send(self, note: Notification) -> NotifyResult: ...
```

- **`url`** — explicit arg › `$DOS_WEBHOOK_URL` › the workspace `.env`
  (`<root>/DOS_WEBHOOK_URL`) — the exact `resolve_token` ladder `notify_slack` uses,
  generalized to a URL. No URL anywhere → `NotifyResult(delivered=False, detail="no
  webhook URL …")` (fail-soft, never a raise — the Slack `no-token` behavior).
- **`token`** — optional bearer/secret. If set, sent as an `Authorization: Bearer
  <token>` header (override-able via `headers`). Pulled from `$DOS_WEBHOOK_TOKEN` /
  `.env` by the same ladder. Many incoming-webhook URLs carry the secret in the path
  (Slack/Teams/Discord style) and need no token; PagerDuty-style needs a routing key —
  both are supported (path-secret = no token; header-secret = token).
- **`dry_run`** — render the JSON body + report what *would* POST, send nothing. (The
  `SlackNotifier` dry-run contract, byte-for-byte.)
- **`method` / `headers` / `timeout`** — the small HTTP knobs; `POST` + `Content-Type:
  application/json` by default.
- **`transport`** — inject a fake in tests (the `client=` injection point Slack uses);
  `None` builds nothing — `send` calls `urllib.request.urlopen` lazily.

### 1a. The payload (pure, local — the `build_blocks` analogue)

A `build_payload(note) -> dict` (pure, no I/O) turns a `Notification` into a flat,
maximally-portable JSON object — NOT a vendor wire format (no Slack Block Kit, no
PagerDuty `payload.severity` enum). The DOS-shaped fact, JSON-serialized:

```json
{
  "severity": "URGENT",
  "title": "fleet: 0 advancing · 1 stalled",
  "summary": "<the plain-text screen>",
  "fields": [["src", "🔴 STALLED  agent-7"], ["recent verdicts", "3"]],
  "key": "dos-top:/ws",
  "source": "top",
  "text": "[URGENT] fleet: 0 advancing · 1 stalled\n<summary>"
}
```

`Notification.to_dict()` already produces the first six keys — so `build_payload` is
`note.to_dict()` plus a synthesized **`text`** convenience field (`[SEVERITY] title\n
summary`), because most chat webhooks (Teams/Discord/Slack-incoming) render a top-level
`text` and ignore the rest. So one body works for *both* a structured consumer (reads
`fields`/`severity`) and a dumb chat hook (renders `text`). A consumer that needs a
vendor-exact shape (PagerDuty's nested `payload`) is a later payload-shaping subclass;
the generic body is the 90% adapter.

### 1b. `send` — fail-soft HTTP, never a raise

```
resolve url (arg › env › .env); none → NotifyResult(delivered=False, "no webhook URL")
dry_run → NotifyResult(delivered=False, "[dry-run] would POST to <url> (SEV: title)")
build_payload → json.dumps → urllib POST with headers + timeout
  2xx           → NotifyResult(delivered=True,  "posted HTTP <code>")
  non-2xx       → NotifyResult(delivered=False, "HTTP <code>: <reason>")
  URLError/etc. → NotifyResult(delivered=False, "error: <e>")     (the inner net)
```

Every failure path returns a `NotifyResult`; `send` **never raises** — the
`SlackNotifier` inner-net discipline, and `send_safely` is the outer net over it. The
`urllib` import is lazy/at-call (stdlib, so it can't fail to import, but kept local for
parity and to keep the module import-clean).

## 2. Registration (the one-line wiring)

`pyproject.toml`, under the existing `dos.notifiers` group beside `slack`:

```toml
[project.entry-points."dos.notifiers"]
slack = "dos.drivers.notify_slack:SlackNotifier"
# A generic HTTP-POST transport (docs/267): renders a Notification to a portable JSON
# body and POSTs it to a configured URL — reaching Teams/Discord/PagerDuty/Opsgenie/
# Zapier/any homegrown endpoint. Stdlib-only (urllib), so it needs NO extra and ships
# in the core. `resolve_notifier("webhook")` finds it by name; the kernel imports none.
webhook = "dos.drivers.notify_webhook:WebhookNotifier"
```

No new extra (it is stdlib). The CLI `dos notify {decisions,top} --notifier webhook
--url …` path already exists — `resolve_notifier` forwards constructor kwargs
(`url=`/`token=`/`dry_run=`), exactly as it forwards `channel=`/`token=` to Slack. So no
CLI change is needed beyond confirming the existing `--notifier`/`--channel`-style flags
carry a `--url` (a small `cmd_notify` widening, if absent).

## 3. The litmus tests this keeps green (mirrors `test_notify_slack.py`)

- **`build_payload` is pure + portable.** A fixed `Notification` → the expected dict
  with `severity`/`title`/`fields`/`source` + the synthesized `text`. No I/O.
- **Routing: a POST happens with the body.** Inject a fake transport; assert one POST
  to the resolved URL carrying the JSON body. (`test_decisions_digest_posts` analogue.)
- **`dry_run` sends nothing.** `delivered=False`, detail contains `[dry-run]`, the fake
  transport saw zero POSTs.
- **Fail-soft — no URL.** No arg/env/`.env` → `delivered=False`, detail names the
  missing URL, no POST. (`test_no_token_degrades_to_skip` analogue.)
- **Fail-soft — non-2xx.** Fake transport returns 500 → `delivered=False`, detail
  carries the code; no raise.
- **Fail-soft — transport raise.** Fake transport raises `URLError` → `delivered=False`,
  `detail` starts `error:`; `send_safely` also wraps it. (`test_transport_raise_is_caught`
  + `test_send_safely_wraps_the_driver_too` analogues.)
- **URL resolution ladder.** explicit › `$DOS_WEBHOOK_URL` › `<root>/.env` — three
  tests mirroring `resolve_token`.
- **Header/token.** A `token` set → an `Authorization: Bearer` header on the request;
  custom `headers` merge/override.
- **Kernel-imports-no-driver holds.** The driver `from dos.notify import …`; nothing in
  `src/dos/*.py` (non-driver) imports `notify_webhook` — re-asserted by the existing
  vendor-agnostic kernel test (the seam imports no transport).

## 4. Scope fence (what this is NOT)

- **It is not a vendor-exact PagerDuty/Teams driver.** It POSTs a *generic* DOS-shaped
  body. A consumer that needs PagerDuty's nested `payload.severity`/`dedup_key` enum is
  a later subclass that overrides `build_payload` — cheap, because the transport
  plumbing (URL/headers/fail-soft/dry-run) is inherited. The generic body already works
  for every chat platform's incoming webhook (top-level `text`) and any automation hook.
- **It does not retry or queue.** A failed POST returns `delivered=False`; the host
  decides whether to re-`dos notify` (the advisory floor — DOS reports, it does not own
  a delivery guarantee). A delivery SLA is a transport's job, not the kernel's.
- **It does not sign requests** beyond the optional bearer token. HMAC-signed webhooks
  (GitHub-style `X-Hub-Signature`) are a payload-shaping subclass concern, not the
  generic adapter's.
- **Advisory, by construction (docs/99).** It reads a projection → POST. No lease, no
  run-stop, no state mutation — identical to `SlackNotifier`.

## 5. See also

- docs/225 (notification spine) — the seam this fills the second slot of; the
  `Notification`/`Notifier`/`send_safely`/`null` contract `WebhookNotifier` implements;
  the "PagerDuty / email / a webhook are later drivers" line this closes.
- `src/dos/notify.py` — the seam (Protocol + `send_safely` + `resolve_notifier`
  forwarding constructor kwargs) the driver plugs into.
- `src/dos/drivers/notify_slack.py` — the sibling transport this mirrors field-for-field
  (constructor shape, `resolve_token` ladder → `resolve_url`, dry-run, inner-net
  fail-soft, injected `client`/`transport` for tests).
- docs/266 (the verdict exporter) — the *event-stream* outward connector; this is the
  *projection-snapshot* one. Together they push both of DOS's outward surfaces (the
  decision/status projections and the verdict stream) off the local machine.

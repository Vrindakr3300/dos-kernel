# RND — Renderer-seam plan (Axis 4: pluggable output)

> **Status:** ✅ **SHIPPED** (all three phases, 2026-06-01). Third in the
> genericization series ([SCV](70_stamp-convention-plan.md) →
> [WCR](71_workspace-config-readback-plan.md) → RND →
> [ADM](73_admission-predicate-plan.md)). Independent of SCV/WCR (presentation
> only). Built on `src/dos/render.py` (`Renderer` protocol + `BaseRenderer` +
> `Text`/`Json` built-ins + `resolve_renderer` + `dos.renderers` entry-point
> discovery), the global `--output` flag wired into
> `verify`/`arbitrate`/`man`/`decisions` (the four decided-object surfaces; not
> `lease`/`journal`, which emit no decided object — see Out of scope), and
> `examples/dos_ext/` made installable (`pip install -e` registers `terse`).
> Pinned by `tests/test_render.py` (34 cases across the three phases, including
> the crash-safety stderr-note assertions). Every default-path output stays
> byte-identical; the North-star snippet runs green end-to-end.

## The gap this closes

HACKING.md Axis 4 is 🔜 *design*: output is hardcoded `print` in `cli.py` and
`render_text` / `render_json` in `timeline.py`. A workspace that wants a different
shape — a one-line terse status-bar form, a colorized TUI, an HTML fragment, a
Slack block — can't get one without forking. The shape of the seam is already
sketched (`examples/dos_ext/renderer.py` ships a working `TerseRenderer` with
`name`, `render_decision`, `render_verdict`), and HACKING.md §4 *documents*
`--output <name>` — **but the resolver and the `--output` flag do not exist.**
This plan builds the resolver, wires the flag, and makes the example real.
(The README only lists "output renderers" among the hackability surfaces; once
RND ships, the now-real `--output` flag is added to the README too — see Phase
3c — so the docs and the code finally agree.)

This is the **lowest-risk axis**: a renderer is *pure presentation*, strictly
downstream of the kernel. A buggy renderer produces ugly text — it can never
mis-admit a lease or mis-verify a ship. So RND can land independently and early.

## Design law this plan must honor

- **Rendering is downstream of the kernel; presentation never leaks policy
  back.** A `Renderer` reads decision/verdict *fields* and returns a string. It
  receives already-decided objects (`LaneDecision`, `ShipVerdict`) — it is handed
  no config, no leases, nothing it could use to decide. This is the one invariant
  that keeps the open renderer set safe (the Axis-4 design rule in HACKING.md).
- **Built-ins stay built-in and total.** `text` and `json` ship in the package
  and are always available; a workspace *adds* renderers, never removes the
  base two. `--output` with an unknown name fails loud with the list of known
  renderers (the completeness posture), never silently falls back.

## North-star acceptance (the whole plan is done when)

```bash
pip install -e examples/dos_ext          # registers the `terse` renderer entry_point
dos verify --workspace . --output terse PLAN PHASE      # one-line terse form
dos verify --workspace . --output json  PLAN PHASE      # machine-readable (built-in)
dos arbitrate --output terse --lane api --kind cluster --leases '[]'
dos verify --output bogus PLAN PHASE     # error: unknown renderer 'bogus'; known: text, json, terse
```

…with `text` as the default (every command byte-identical to today when
`--output` is omitted).

---

## Phase 1 — the `Renderer` protocol + built-ins behind it (the throughline) ✅

The smallest end-to-end slice: route *one* command's output through a resolver
whose only registered renderers are the two built-ins — no behavior change.

- **1a.** Add `dos/render.py`: the `Renderer` `Protocol` (`name: str`,
  `render_decision(decision) -> str`, `render_verdict(verdict) -> str`), plus
  `TextRenderer` and `JsonRenderer` that reproduce today's `cli.py` /
  `timeline.py` output **byte-for-byte**. A `BUILTIN_RENDERERS = {"text":…,
  "json":…}` map.
- **1b.** Add `resolve_renderer(name) -> Renderer`: look up `name` in the
  built-in map; raise `UnknownRenderer(name, known=[…])` on a miss. (Entry-point
  discovery is Phase 2 — Phase 1 resolves built-ins only, so the throughline has
  zero new dependency surface.)
- **1c.** Route `cmd_verify`'s output through `resolve_renderer("text")
  .render_verdict(verdict)`. One command, default renderer, identical bytes.

**Litmus (Phase 1):**
- `tests/test_render.py::test_text_renderer_byte_identical_verdict` — the
  `TextRenderer.render_verdict` output equals the current `cmd_verify` print,
  char-for-char, on a frozen `ShipVerdict` fixture (+ `_not_shipped_no_sha` /
  `_no_source_omits_via` for the conditional-fragment branches).
- `test_json_renderer_roundtrips_verdict` / `_is_sorted_keys` — `JsonRenderer`
  output parses back to the verdict's `to_dict()` AND equals the old `--json`
  bytes (`sort_keys=True`).
- `test_resolve_unknown_raises_with_known_list` — `resolve_renderer("nope")`
  raises with the known-list in the message.

---

## Phase 2 — entry_point discovery + the `--output` flag (make it pluggable) ✅

- **2a.** Extend `resolve_renderer` to also consult the `dos.renderers`
  entry-point group via `importlib.metadata.entry_points`. Resolution order:
  built-in names first (a workspace can't shadow `text`/`json` — they're the
  trusted fallback), then registered plugins. A plugin whose `name` collides with
  a built-in is ignored with a one-line stderr note (don't let a plugin silently
  capture `json`).
- **2b.** Add a global `--output <name>` argument (default `text`) to the CLI
  parser, threaded into every command that emits a decision/verdict
  (`verify`, `arbitrate`, `lease`, `journal`, eventually `decisions`). Each
  command resolves once and calls the renderer.
- **2c.** Make `examples/dos_ext` a real installable: give it the
  `[project.entry-points."dos.renderers"] terse = "dos_ext.renderer:TerseRenderer"`
  it documents, so `pip install -e examples/dos_ext` actually registers `terse`.

**Litmus (Phase 2):**
- `test_entrypoint_renderer_discovered` — with a stub entry-point registered in
  the test (via an installed fixture package or a monkeypatched
  `entry_points`), `resolve_renderer("terse")` returns it.
- `test_builtin_cannot_be_shadowed_by_plugin` — a plugin claiming `name="json"`
  does not displace the built-in `JsonRenderer`, and the collision is noted on
  stderr (not silently captured).
- `test_unknown_name_does_not_double_warn_on_collision` — an unknown `--output`
  plus a colliding plugin emits the collision note exactly once (discovery runs
  once per resolve, reusing its dict for the error's known-list).
- `test_output_json_matches_json_flag` / `_output_text_is_default` /
  `_output_bogus_fails_loud` / `_arbitrate_default_is_compact_json` /
  `_arbitrate_pretty_still_indents` — the North-star `--output` snippets run as
  specified, and the default/`--json`/`--pretty` paths stay byte-identical.

---

## Phase 3 — extend the protocol to the remaining surfaces ✅

> **Shipped note (2026-06-01):** the protocol grew the optional surfaces
> (`render_timeline` / `render_man` / `render_decisions`), each defaulting to the
> text form via `BaseRenderer` so a partial renderer is still total. `cmd_man`
> now assembles a `ManEntry` (decided content) and routes through the seam —
> default `text` output byte-identical, `--output json` emits structured fields.
> `timeline.render_text`/`render_json` are reached through the `Text`/`Json`
> renderers' `render_timeline` (byte-identical, pinned). The standalone
> `timeline.main()` keeps its own `--json` (it is not a `dos` subcommand, so it
> grows no `--output`); the *seam* over its renderers is what shipped. The
> example `TerseRenderer` implements one optional surface (`render_timeline`) to
> demonstrate the partial pattern; `render_man`/`render_decisions` fall back to
> text. HACKING.md §4 flipped 🔜 *design* → ✅ *shipped*.

The protocol in Phase 1 covers decision + verdict. The other output-producing
surfaces (`timeline`, `man`, `decisions`) currently render themselves.

- **3a.** Grow the `Renderer` protocol with optional methods —
  `render_timeline(timeline)`, `render_man(entry)`, `render_decisions(rows)` —
  each defaulting (via a base class) to the text form, so a renderer that only
  cares about verdicts doesn't have to implement all of them.
- **3b.** Route `timeline.render_text`/`render_json` and `cmd_man` through the
  resolver, preserving byte-identical default output (the same
  byte-identical litmus as Phase 1, per surface).
- **3c.** Document the full protocol in HACKING.md §4, flipping its status from
  🔜 *design* to ✅ *shipped*, and update `examples/dos_ext/renderer.py` to show
  one optional method implemented (e.g. `render_timeline`) so the skeleton
  demonstrates the partial-implementation pattern.

**Litmus (Phase 3):**
- Per-surface byte-identical tests for the default `text` renderer
  (`test_text_renderer_timeline_byte_identical` /
  `test_json_renderer_timeline_byte_identical`; `test_cmd_man_default_text_byte_identical`
  / `test_cmd_man_json_is_structured`; the decisions list surface byte-identity
  via `test_cmd_decisions_*`) — proves routing through the seam changed nothing
  for the default path.
- `test_partial_renderer_falls_back_to_text_for_timeline` — a renderer
  implementing only `render_verdict`/`render_decision` still produces text for
  `render_timeline` (the `BaseRenderer` fallback).
- `test_buggy_plugin_method_falls_back_to_text` — a plugin renderer whose method
  *raises* degrades to the built-in text form with a stderr note rather than
  crashing the command (the renderer-can-only-uglify safety invariant).

---

## Out of scope (explicitly)

- **Renderers deciding anything.** A renderer is handed decided objects and
  returns a string — full stop. If a "renderer" needs config or leases, it's not
  a renderer; that's a different axis.
- **TOML-declared renderers.** Renderers are code → `entry_points`, never
  `dos.toml` (the data/behavior split in HACKING.md). A workspace's `[output]`
  *default-selection* (which named renderer to use absent `--output`) *could* be
  data — defer that to a follow-up; Phase 2's `--output` flag covers the need.
- **The decisions-TUI curses layer.** `decisions_tui.py` is an interactive
  surface, not a one-shot string render; bringing it under the protocol is a
  larger follow-up, not part of RND. *(Shipped reality: the one-shot decisions
  LIST surface — `dos decisions --no-tui`/`--output …` — DOES route through the
  seam via `render_decisions`; only the curses TUI and the per-decision `show
  <#>` detail pane stay off it.)*
- **`dos lease` / `dos journal` `--output`.** Phase 2 listed them, but neither
  emits a `ShipVerdict`/`LaneDecision` (lease prints lock STATUS; journal prints
  raw WAL entries). With no decided object the renderer contract applies to,
  threading `--output` into them would be a flag that selects nothing — so they
  keep their own `--json`/text output and are explicitly out of RND's
  decided-object seam. A future "lease/journal as decided objects" surface is a
  separate item if a consumer needs it.

## Why this is third

It's the safest axis (pure presentation) and fully independent of SCV/WCR, so it
can slot in whenever convenient — but it's *third* because making `verify` and
`arbitrate` themselves generic (SCV, WCR) is higher-leverage than making their
output pluggable. RND turns the already-sketched, HACKING-documented `--output`
seam into a real one, closing the gap between what HACKING.md §4 describes and
what ships (and updating the README to advertise the now-real flag).

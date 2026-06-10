# DOS drivers — the copy-me host policy pack (layer 4)

> **The kernel is the part that doesn't believe the agents.** A *driver* is the
> part that tells the kernel which lanes your host has and how they may run
> together — the policy, not the mechanism.

This directory holds [`example_host.py`](example_host.py), a **minimal copy-me
driver**: the smallest module that is a real DOS host policy pack. It is the
rung-5 deep case for an adopter who needs *provider/behavioral policy that can't
be expressed as data*. **Most adopters never need a driver** — see "Do you even
need one?" below first.

## What a driver is

A driver is a **layer-4 policy pack**: the dull-but-load-bearing part outside the
kernel boundary that says which lanes a host has, how they admit concurrency, and
where its state lives. The kernel ships *mechanism* (`verify` / `arbitrate` /
`liveness` / the refusal vocabulary); a driver supplies the *policy* those
syscalls read instead of hardcoding it. It is exactly two things:

1. a **`LaneTaxonomy` constant** — the concurrency policy as pure data
   (`concurrent` / `exclusive` / `autopick` / `trees` / `aliases`), and
2. an **`<name>_config(workspace)` factory** — binds that taxonomy to a workspace
   root and returns a `SubstrateConfig`.

## How a driver is wired — BY CONVENTION

There is **no entry-point and no `dos.toml` key** for a driver. The wiring is the
module name alone. The generic CLI loader behind `dos --driver <name>`:

```
dos --driver example_host  doctor --workspace .
        │
        └─► imports  dos.drivers.example_host
            and calls  example_host.example_host_config(workspace)
```

So the contract is purely **`dos.drivers.<name>.<name>_config`**: the factory
name MUST match the module stem. `--job` is just the back-compat alias for
`--driver job`. A driver name is a single module token (a dotted/path-y name is
rejected up front). This is what lets a new host be added as one module without
the CLI ever learning its name — the same one-way dependency arrow the kernel
obeys. (Verified at `src/dos/cli.py` `_resolve_driver_config`.)

> Drivers are discovered as submodules of the `dos.drivers` package. To make your
> module importable as `dos.drivers.<name>` you either drop it next to the
> shipped drivers in an editable checkout, or ship it from your own package and
> make `dos.drivers` a namespace package (see "Copy it into a real consumer").

## Do you even need a driver? (Usually not.)

A workspace's own `dos.toml` **overrides** a `--driver` pack. The CLI resolution
order, highest precedence first, is:

> **`dos.toml` tables  ›  `--driver <name>` pack  ›  the generic `default_config`**

So a `dos.toml [lanes]` table wins over a driver's `LaneTaxonomy`, `[stamp]` wins
over its stamp grammar, and `[paths]` wins over its layout. (Verified at
`src/dos/cli.py` `_apply_workspace`.)

That means **most adopters only need a `dos.toml`** (run `dos init .` to scaffold
one — it auto-derives a `[lanes]` table from your top-level dirs) plus maybe a
custom renderer (a `dos.renderers` plugin — see
[`../dos_ext/`](../dos_ext/)). Reach for a driver **only** when your policy
genuinely cannot be data:

- behavioral/provider policy that needs Python (a custom path layout computed at
  runtime, a programmatic `PathLayout` swap), or
- you want to ship a reusable host pack as code that callers select with one
  `--driver <name>` flag rather than copying a `dos.toml` into every checkout.

If your need is "different lanes / different ship-stamp grammar / different state
paths," that is **data** — declare it in `dos.toml`, skip the driver.

## The minimal required shape

A driver needs only **lanes + paths + the factory**. `reasons` and `stamp` are
**OPTIONAL** (they default to the generic base and are layered from `dos.toml` if
declared). The factory MUST follow this exact body:

```python
def example_host_config(workspace=None):
    root = resolve_workspace_root(workspace)
    return SubstrateConfig(
        lanes=EXAMPLE_HOST_LANE_TAXONOMY,
        paths=PathLayout.for_root(root),
        workspace=gather_workspace_facts(root),   # MANDATORY — see below
    )
```

### `gather_workspace_facts(root)` is MANDATORY

It is not decoration. It caches *which kernel runtime files exist under this root*
so the pure **SELF_MODIFY guard** is workspace-scoped. Omit it and
`config.workspace` is `None`, which forces the guard to its conservative full
static set and can **wrongly refuse** a whole-repo lane in a foreign checkout. A
driver factory MUST gather facts, exactly as the kernel's own factories
(`default_config` / `job_config`) do.

> Building the taxonomy from a directory scan instead of by hand? Use the public
> helper `from dos.lane_infer import infer_lanes_from_directory` — it returns the
> same typed `LaneTaxonomy` `dos init` scaffolds, ready to drop into
> `SubstrateConfig(lanes=...)`.

## Copy it into a real consumer

1. **Copy** [`example_host.py`](example_host.py) into your repo (or your own
   installable package).
2. **Rename** the module file and every `example_host` token to your host's name
   — both the `EXAMPLE_HOST_LANE_TAXONOMY` constant *and* the
   `example_host_config` factory (the factory name must match the new module
   stem).
3. **Edit the `LaneTaxonomy`** for your repo: which dirs are concurrent
   (tree-disjoint) lanes, which are exclusive, the autopick order. (Tip:
   `dos init .` shows the lanes it would derive from your layout.)
4. **Make it importable as `dos.drivers.<name>`** — drop it beside the shipped
   drivers in an editable `dos-kernel` checkout, or ship it from your package as
   part of a `dos.drivers` namespace package.
5. **Select it:** `dos --driver <name> doctor --workspace .` and confirm your
   lanes appear. From then on, `dos --driver <name> arbitrate --lane <L> ...`
   uses your policy (unless a `dos.toml` in that workspace overrides it).

Keep all imports from `dos.config` only (`LaneTaxonomy`, `PathLayout`,
`SubstrateConfig`, `gather_workspace_facts`, `resolve_workspace_root`) — a driver
imports the kernel, never the other way around.

## See also

- [`src/dos/drivers/workshop.py`](../../src/dos/drivers/workshop.py) — the
  **rich reference** driver: concurrent tree-disjointness, the shared-`docs/`
  filename-prefix trick, an exclusive whole-repo lane, and keyword aliases, all
  fully annotated. Read it when `example_host.py` leaves you wanting the why.
- [`docs/HACKING.md`](../../docs/HACKING.md) — the full extension contract (the
  closed-enum-as-data pattern, renderers, predicates, judges).
- [`../dos_ext/`](../dos_ext/) — the extension skeleton for the *data + code*
  axes (reasons in `dos.toml`, renderers / predicates / judges via
  entry-points) — the things that are NOT a driver.

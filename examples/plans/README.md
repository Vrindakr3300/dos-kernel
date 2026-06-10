# Example plan docs — the shape `dos plan` reads

This directory holds **[`example-plan.md`](example-plan.md)**: a copyable starter
plan that round-trips with DOS's built-in `markdown` plan source
(`src/dos/plan_source.py`). It exists because the rest of `examples/` ships
`dos.toml` *workspace* fixtures but no *plan* doc — so when someone asks "what does
a plan file actually look like," this is the answer.

A plan doc is **not a schema the kernel believes** — `dos plan` treats it as a
*row source*: it harvests the `(plan, phase)` rows out of this file, then rules on
each with `dos verify` (git ancestry + the ship-stamp grammar), never from the
`SHIPPED` words in the prose. The headline cell of the board is the **divergence**:
where the plan CLAIMS shipped but the oracle says not (`⚠over-claim`). See the
heavily-commented [`example-plan.md`](example-plan.md) for the full grammar.

## Run the board against it

The default `plans_glob` is `docs/**/*-plan.md`, so the file is discovered when it
lives under `docs/` and ends `-plan.md`. Two ways to point `dos plan` at it:

**A. Drop it under `docs/` (zero config).** Copy the file into your repo's `docs/`
and run the board:

```bash
cp examples/plans/example-plan.md docs/auth-plan.md
git add docs/auth-plan.md && git commit -m "add auth plan"
dos plan --workspace . --once          # one plain-text frame (CI / pipe)
dos plan --workspace . --json          # the machine-readable snapshot
```

**B. Point `plans_glob` at this dir (no move).** Override the one layout field in
`dos.toml` (`[paths]` overrides only the keys you name; the rest inherit the
default — see [`docs/HACKING.md`](../../docs/HACKING.md)):

```toml
# dos.toml
[paths]
plans_glob = "examples/plans/*-plan.md"
```

Then `dos plan --workspace . --once` harvests `example-plan.md` directly.

**C. No plan doc at all — fan the oracle over explicit pairs.** The purest mode:
positional `plan phase` pairs need no file, no schema:

```bash
dos plan --workspace . AUTH AUTH1 AUTH AUTH2     # board over an explicit row list
```

## What you'll see

Harvested live from `example-plan.md`, the board shows three rows and the
believed-vs-adjudicated split — verified end to end:

| phase | plan claims | oracle (git) | board cell |
|---|---|---|---|
| `AUTH1` | shipped | `NOT_SHIPPED (via none)` until a `AUTH1:` commit | **`⚠over-claim`** |
| `AUTH1` | shipped | `SHIPPED (via grep)` once `AUTH1: …` is committed | `✓shipped` |
| `AUTH2` | open | not shipped | `·pending` |
| `AUTH3` | blocked (soak) | not shipped | `·pending` |

The `⚠over-claim` row is the whole reason the board exists: the plan said done, the
oracle checked git and disagreed. Stamp it for real with a commit whose subject
starts `AUTH1:` (the generic default ship grammar, same as the
[`README`](../../README.md) / [`QUICKSTART`](../../docs/QUICKSTART.md)) and the cell
flips to `✓shipped`.

## Two gotchas worth knowing

- **Phase-id grammar is strict on purpose.** A phase token must carry **both a
  letter and a digit** (`AUTH1`, `P2`, `IF4.1`); a bare ordinal (`2`, `1a`) is
  rejected. DOS's OWN `docs/NN_*.md` design plans use a different dialect
  (`### Phase 2:`) the default does NOT read — copy `example-plan.md`, not a design
  doc. A repo on that dialect ships a `dos.plan_sources` plugin instead (the
  by-name plan-source seam; see [`docs/HACKING.md`](../../docs/HACKING.md)).
- **Claim-words leak from comments.** The source reads a phase's *whole section
  text* (HTML comments included) when deciding the claimed status, so a bare
  `SHIPPED` / `SOAK` token inside an explanatory comment under an *open* phase will
  flip it to claimed-shipped/blocked. Keep the stamp tokens out of comments under a
  phase you mean to leave open (`example-plan.md`'s AUTH2 comment shows the safe
  wording).

## Custom plan dialects

If your plans don't match the built-in grammar — a different heading shape, a YAML
front-matter plan, a plan registry — register a **`dos.plan_sources`** plugin (the
plan-source seam: a `name` + a `rows(config) -> list[PlanRow]` method, resolved by
name, fail-to-empty). The kernel default never guesses your format; a plugin is how
you teach it. Full how-to in [`docs/HACKING.md`](../../docs/HACKING.md).

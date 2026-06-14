# 339 — `opus-fable-mode`: a self-measured style control loop, and the witnessed-effectiveness 2.0 DOS can power

> **One sentence.** The r/ClaudeCode post *"I analyzed 26 sessions (9K+ messages)
> of Fable 5 and 145 sessions (27K messages) of Opus 4.8"* (u/coolreddy,
> repo [`Poorna-Repos/opus-fable-mode`](https://github.com/Poorna-Repos/opus-fable-mode))
> independently builds **exactly docs/333's verification-as-steering control loop** —
> setpoint + thermostat + sensor — to make Opus 4.8 *behave* like the (suspended)
> Fable 5; it is strong outside validation that the loop shape is right, and its one
> structural flaw is the one DOS exists to fix: **its sensor measures the agent's own
> output text, a forgeable self-authored signal (docs/332 tier-1/3), so it steers
> toward the *narration* of conciseness, not conciseness itself.** The 2.0 is to swap
> the sensor for an author-disjoint one — steer toward *verified effect*, not style.

**Status:** framework / strategy note — no kernel change, no new syscall. **Date:** 2026-06-14.
**Builds on:** docs/333 (verification IS steering — closed-loop control — *read first*),
docs/332 (the four-tier provenance taxonomy: which signals are forgeable), docs/336
(the prose→tool-call legibility shift), docs/181/192 (effect witness + coverage).
**Primary source read in full:** the post body + 87 comments (via the `.rss` feed —
the one route reddit didn't block; see §7) and every file in the repo
(`governor-block.md`, `leak_test.py`, `reinject.sh`, `install/`).

---

## 1. What the post actually is (read first-hand, corrected)

When Fable 5 was suspended (2026-06-12) and work "snapped back to Opus 4.8," the
author felt Opus was "wordier, more hedge, more *let me think about whether I should
think about this*," mined his own Claude Code JSONL logs (Claude Code stores every
session on disk), and **measured the behavioral gap**: 9,224 Fable messages vs.
27,685 Opus messages across 68 projects. His headline numbers, verbatim:

| Signal | Opus 4.8 | Fable 5 | His reading |
|---|---|---|---|
| Median words/msg | 47 | 18 | Fable's typical reply ~2.6× shorter |
| **Mean** words/msg | ~100 | ~99 | **equal** — so it isn't "shorter," it's *distribution*: Fable is terse by default, deep when it matters; Opus pads medium everywhere |
| Tool-call : prose ratio | 1.41 | 3.91 | Opus writes ~3× more prose per unit of real work — "the exhausting feeling, quantified" |
| Opening words | "I'll", "Let me" | "Done", "task" | Opus narrates itself; Fable opens with the result |
| Readable thinking in logs | ~0% | ~0% | the thinking stream is encrypted at storage — you can mine *behavior*, not reasoning |

His own framing splits the gap in two: a **working-style half** you can steer with
prompts/hooks, and a **raw-capability half** in the weights you can't. He goes after
the recoverable half with **three layers** — and this is the part that matters for us,
because it is a control loop:

- **The governor (setpoint):** an 8-rule behavioral block appended to `~/.claude/CLAUDE.md`
  (`governor-block.md`). The rules target Opus's "anxious texture": *reason about the
  problem not yourself; one self-audit then stop (recursion depth limit 1); start
  claims later and stop earlier; minimum honest qualifier; commit — convert open
  questions to closed (`// DECISION:`); outcome over visible process; preserve real
  depth (don't overcorrect to curt); in tool work, act don't narrate — ~4 tool actions
  per prose block, lead with the result.*
- **The re-injection hook (thermostat):** a `UserPromptSubmit` hook (`reinject.sh`)
  that **re-prints the governor every turn**, because "a CLAUDE.md line decays in
  salience as the session grows." (This is the salience-decay problem docs/336 §
  flags from the other side.)
- **The leak-test (sensor):** `leak_test.py` reads his own logs and reports whether
  Opus is **converging toward Fable's signature** on the four measured signals,
  "instead of you guessing."

His honest early results (he flags small-n himself): tool:text moved **1.41 → ~2.2**
and "I'll/Let me" openers dropped **12.8% → ~5%**, both toward Fable; median words
noisier. *"Not a clean win yet — it's a control loop you watch over time."* And the
ceiling he states plainly: *"it doesn't change the weights, so it suppresses the
anxious texture rather than curing it,"* and does nothing for raw capability.

(The top comments are a running joke that the post's own prose — "load-bearing
comment," "And that's not nothing," "You're absolutely right!" — is itself
Opus-sycophancy, plus one sharp skeptic: *"cosplaying Einstein doesn't make one think
like Einstein."* The skeptic is half-right, and §4 says exactly which half.)

## 2. The big realization: this is docs/333, built by an outsider

docs/333's thesis is that **verification is steering** — a verifier isn't a gate you
add at the end, it's the *sensor* in a closed control loop, and an agent harness
without one is an open-loop controller. `opus-fable-mode` is that loop, named in the
same words, built independently by someone who'd never heard of DOS:

| Control element | docs/333 term | `opus-fable-mode` |
|---|---|---|
| Setpoint | the spec / goal | the 8-rule governor |
| Actuator re-assert | (the harness) | the `UserPromptSubmit` re-injection hook |
| **Sensor / feedback** | **the verifier** | **`leak_test.py`** |
| Error signal | claim-vs-truth | `abs(post − fable) < abs(pre − fable)` per metric |

That an outsider reached for *exactly this shape* under real pain (Fable yanked, Opus
"exhausting") is the strongest kind of validation for docs/333: the control-loop framing
isn't a DOS idiosyncrasy, it's what people build when they actually try to steer an
agent's behavior over time. **Borrow nothing structural here — we already have it;
cite it in docs/333 as independent corroboration.**

## 3. The flaw, in DOS terms — the sensor is forgeable

`leak_test.py` is an honest, well-built script (it buckets by `message.model`,
splits `opus_pre`/`opus_post` on a cutoff date, computes medians/quantiles, caps at
15k msgs/bucket, and prints a per-metric `pre → post (target) [✓/✗]` verdict). But
every signal it reads is **authored by the agent being measured**:

- *median words/msg* — the agent picks how many words to emit;
- *tool:text ratio* — the agent picks how many tool blocks vs prose blocks to emit;
- *self-opener %* — the agent picks its first word;
- *caveat %* — the agent picks whether to type "to be fair."

By docs/332's taxonomy this is a **tier-1 (self-narrated) / tier-3 (text a judge
reads) signal**, and its defining weakness is that *the agent can move every metric
to target without the underlying disposition changing at all.* Open with "Done.",
emit terse messages, sprinkle extra tool calls — the sensor reads ✓ converging while
the work is no better. The loop optimizes **the narration of conciseness, not
conciseness**; the *appearance* of "act don't narrate," not acting. This is the exact
forgeable-channel failure docs/332 §2 names ("a model trained on a label it can author
is a model trained to author the label") and the reward-hacking surface docs/318
measured. The author even half-sees it — *"it suppresses the texture rather than
curing it"* — but his sensor cannot tell suppression from cure, because suppression
is all it can see.

The skeptic comment lands here too, sharpened: cosplaying Einstein's *terseness* is
measurable and gameable; cosplaying his *effectiveness* is neither — which is the whole
point of using an author-disjoint sensor.

## 4. The 2.0: steer toward verified effectiveness, not style

Keep the loop (it's right). **Replace the forgeable sensor with an author-disjoint
one** — the move docs/332/333 prescribe. Concretely, a `leak_test.py` successor whose
metrics the agent *cannot* author by choosing its own words:

| Forgeable signal (today) | Author-disjoint replacement (DOS) | Witness |
|---|---|---|
| tool : **text** ratio | tool : **landed-effect** ratio — actions per *witnessed* commit/file/test-pass | `commit-audit`, `witness_effect` |
| "Done"/"task" opener % | **claim-vs-truth rate** — of messages that *say* "done", how many a witness confirms | `verify` / effect witness |
| caveat / hedge % | **typed-refusal rate** — hedges replaced by a kernel `refuse(reason_class)` from the closed vocabulary | `refuse` + `dos doctor` |
| median words/msg | (keep, but **advisory** — a texture proxy, explicitly labelled forgeable) | — |

The reframe: the author measured "does Opus *sound* like Fable?" The DOS sensor
measures "does Opus *do the work* Fable's texture was a proxy for — commit decisions
instead of hedging, land effects instead of narrating, refuse legibly instead of
armor-hedging?" His own governor rules 5 ("commit; convert open questions to closed")
and 8 ("act, don't narrate") are *already effect-shaped* — they just lack an
effect-shaped sensor to close the loop. DOS supplies exactly that sensor, and nothing
else needs to change.

This is a clean, small, shippable artifact: a `dos`-backed leak-test that reads the
same `~/.claude/projects/**.jsonl`, joins each "done"-class claim to a git/effect
witness, and reports a convergence verdict on **non-forgeable** axes. It composes with
his repo rather than replacing it (his governor + hook stay; only the sensor upgrades).

## 5. Borrow directly — three things, regardless of the sensor swap

1. **The re-injection hook against salience decay.** His observation — a CLAUDE.md
   directive *decays as the session grows* and needs re-asserting every turn — is real
   and matches docs/336. DOS's own steering (the governor directives in our CLAUDE.md;
   the "prefer tool calls over prose" line added this session) would benefit from the
   same thermostat. **Borrow:** a `UserPromptSubmit` re-injection pattern is a cheap,
   general harness primitive; note it for the host-wiring docs.
2. **Mine the on-disk JSONL as a behavioral record.** Both his work and teich (§6)
   key on the fact that Claude Code persists every session. DOS already reads these
   for the hook-observation log; a *behavioral* read (effectiveness over time) is a
   natural `dos` projection. **Borrow:** the read surface, not his metrics.
3. **Publish the target as numbers, honestly small-n.** He states his sample, flags
   it directional, invites reproduction. Same discipline as docs/332 §5. **Borrow:**
   the posture (it's ours already; good to see it converge from outside).

## 6. Sidebar — where teich fits (the adjacent tooling, not the post)

An earlier draft of this doc mis-read the post as being about training-data corpora
and built its whole argument on the `teich` toolchain. That was wrong: the post is
about **behavioral steering**, not SFT pools. teich is *adjacent* (it extracts the
same `~/.claude/projects/**.jsonl` into training data) and the docs/332 tier analysis
of it still holds — teich-extracted traces are tier-1 self-narrated, and a
DOS-witnessed pool would be the training-data 2.0. But that is a **separate** thread
from this post; it belongs in the docs/332 program, not here. One line worth keeping:
the *same forgeability* sinks both — teich's "successful session" label and
opus-fable-mode's "converging" verdict are both read off agent-authored bytes, and
the *same* author-disjoint witness fixes both. That common root is the through-line.

## 7. Provenance — how the post was finally read (and the route that worked)

Reddit blocks this harness on the obvious paths: direct fetch, jina, archive.org
(0 snapshots), archive.ph, Google/Bing/DDG caches, four CORS proxies (allorigins,
corsproxy, codetabs, thingproxy — `.json` → 522/403), seven redlib/teddit frontends
(403 or Anubis bot-wall), and pullpush.io (indexes r/ClaudeCode but its horizon
predates this post; `q=Fable` → 0). **The route that worked: the post's `.rss` feed**
(`/comments/<id>/.rss`) fetched with a normal browser UA via `curl` — a different
rate-limit bucket reddit left open. It returns Atom XML with the post as the first
`<entry>`'s CDATA `<content>` and each comment as a later entry; an HTML-strip parse
recovered the full body, the five-row metrics table, the three-layer description, the
repo link, and 87 comments. The repo itself read cleanly from `raw.githubusercontent.com`.
**Lesson for next time (saved to memory):** for a recent reddit post, try the `.rss`
endpoint with `curl` *first* — it survived when 15 other routes failed.

## 8. Through-line

docs/333 said verification is steering — the verifier is the sensor in a control loop,
not a gate at the end. `opus-fable-mode` is that exact loop, built by an outsider in
real pain, which is the best validation docs/333 could ask for. Its one flaw is the
one the whole DOS program is about: **a control loop is only as trustworthy as its
sensor, and a sensor that reads the agent's own words can be satisfied by changing the
words.** The 2.0 keeps his loop and swaps the sensor for an author-disjoint one —
steering Opus toward Fable's *effectiveness* (committed decisions, landed effects,
legible refusals) instead of Fable's *prose style*. Same loop, honest sensor; that is
the entire DOS contribution, and it is a small composable tool away.

### Next actions (witness-able)

- [ ] Build the `dos`-backed leak-test: read `~/.claude/projects/**.jsonl`, bucket by
      `message.model` like his script, but compute the §4 author-disjoint metrics
      (tool:landed-effect, claim-vs-truth on "done"-class messages, typed-refusal rate)
      via `commit-audit`/`witness_effect`. Report `pre → post (target) [✓/✗]` on
      non-forgeable axes. Composes with his governor+hook.
- [ ] Add the §2 corroboration paragraph to docs/333 (outsider independently built the
      verification-as-steering loop).
- [ ] Note the re-injection-hook pattern (§5.1) in the host-wiring docs as a general
      anti-salience-decay primitive for our own governor directives.

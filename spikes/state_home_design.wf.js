export const meta = {
  name: 'dos-state-home-design',
  description: 'Design the .dos/ + DOS_HOME state-home model end-to-end (v1+v2), adversarially verify against the kernel design laws, synthesize a structured design',
  phases: [
    { title: 'Probe', detail: 'independent design probes against the real code' },
    { title: 'Critique', detail: 'adversarial critic hunts breakage of job / seam / litmus' },
    { title: 'Synthesize', detail: 'merge into one structured design + phase breakdown' },
  ],
}

const REPO = '.'  // the repo root (run from a checkout)
const APPDATA_DOS = String.raw`%APPDATA%\dos`
const HOME_DOS = '~/.dos'

const COMMON = [
  `You are designing a feature for DOS, a domain-free trust-substrate Python package at ${REPO}.`,
  `READ the actual code before claiming anything — do not trust your memory.`,
  `Key files: src/dos/config.py (PathLayout, SubstrateConfig, resolve_workspace_root, default_config, job_config),`,
  `src/dos/lane_journal.py, src/dos/archive_lock.py, src/dos/run_id.py, src/dos/decisions.py,`,
  `src/dos/oracle.py, src/dos/picker_oracle.py, src/dos/cli.py, src/dos/stamp.py, src/dos/__init__.py,`,
  `tests/*.py, docs/70_stamp-convention-plan.md and docs/71_workspace-config-readback-plan.md (the plan-doc convention to match),`,
  `CLAUDE.md (the architecture contract).`,
  ``,
  `THE DECIDED DESIGN (user-confirmed — do not relitigate, design WITHIN it):`,
  `- Per-project ".dos/" dir (sibling of dos.toml), gitignored-by-default, AUTO-CREATED on first WRITE.`,
  `  Holds DOS own emissions: runs/RID-<ts><entropy>/ (run dirs keyed by run_id, collapsing job 3 dirs`,
  `  _fanout_runs/_dispatch_loops/_chained_runs), lane-journal.jsonl, leases/ (+ .archive.lock),`,
  `  verdicts/.verdict-*.json, soaks/index.yaml, project.json (identity card).`,
  `- Machine-local DOS_HOME: resolve order DISPATCH_HOME env > XDG_DATA_HOME/dos > (win32) ${APPDATA_DOS} > ${HOME_DOS}.`,
  `  Holds projects/index.jsonl (row per project) + decisions.jsonl (resolved-decision digests). REBUILDABLE projection, never source of truth.`,
  `- Run dirs keyed by run_id (sortable+collision-safe+lineage), not bare UTC.`,
  `- Read-only syscalls (verify/man/doctor/decisions) NEVER write; first persisting syscall lazily ensure_project_home() + one stderr courtesy line.`,
  `- Back-flow = projection-not-sync: "dos reindex" rebuilds central indices by walking each .dos/project.json.`,
  ``,
  `HARD CONSTRAINTS (violating any is a design bug):`,
  `1. job MUST NOT MOVE: job_config() keeps PathLayout.for_root (the docs/_plans layout). Only default_config() adopts .dos/. job consumes dos via "pip install -e" and byte-thin shims; its docs/ layout is sacred.`,
  `2. Kernel imports no host (CLAUDE.md litmus): no module under src/dos/ except drivers/ may name job/apply/tailor. The .dos/ layout is the GENERIC default business.`,
  `3. Layering: home.py would be layer-1 kernel (stdlib + dos.config only). decisions.py stays a pure read-only projection (stores nothing of its own).`,
  `4. The seam already exists: every kernel module reads paths via config.active().paths.* — so this is mostly a PathLayout change. VERIFY that claim against the code; report any consumer that bypasses the seam.`,
  `5. Determinism: run_id.py bans wall-clock/random in reproducible paths (clock/entropy injectable). Central-index writes must follow the same fsync/torn-tail discipline as lane_journal.`,
].join('\n')

phase('Probe')

const PROBES = [
  {
    key: 'layout',
    label: 'probe:layout',
    prompt: [
      COMMON, '',
      'DESIGN PROBE — the .dos/ PathLayout.',
      'Specify EXACTLY how PathLayout gains the .dos/ layout. Read PathLayout.for_root and every field it sets, and read every kernel module that consumes a paths.* field (grep for "config.active().paths", "cfg.paths", "config.paths").',
      'Produce:',
      '1. The complete field-by-field mapping: each current for_root field -> its new .dos/ location. Cover ALL fields incl execution_state, plans_glob, findings_queue, fanout_runs, dispatch_loops, chained_runs, next_packets, replan_dir, soaks_index, picker_audits, archive_lock, lane_journal.',
      '2. CRITICAL DECISION: execution_state and plans_glob describe the REPO plan registry (host truth), NOT DOS scratch. Should they STAY repo-relative (docs/) even in the .dos/ layout, or move under .dos/? Argue it. (Hint: verify() reads the repo plans; moving them would break reading a repo that already has plans.)',
      '3. How the 3 run-dir trees (fanout_runs/dispatch_loops/chained_runs) collapse into one .dos/runs/ keyed by run_id — what carries the old distinction (run_id.process_id?). Which consumers glob those dirs and would need to change.',
      '4. The exact signature: PathLayout.for_dos_dir(root) classmethod, what it returns, and whether next_packets (output/next-up, the verdict envelopes the decisions queue reads) moves under .dos/verdicts/.',
      '5. Back-compat: how default_config switches to for_dos_dir while job_config stays for_root, in code.',
      'Return a precise spec a builder can implement without re-deciding anything.',
    ].join('\n'),
  },
  {
    key: 'home',
    label: 'probe:dos-home',
    prompt: [
      COMMON, '',
      'DESIGN PROBE — DOS_HOME resolution + the central store shape.',
      'Read resolve_workspace_root in config.py (the precedence idiom to mirror) and the env-override idioms in lane_journal.py / archive_lock.py.',
      'Produce:',
      `1. resolve_dos_home() exact implementation: DISPATCH_HOME env > XDG_DATA_HOME/dos > (win32, via sys.platform) ${APPDATA_DOS} > ${HOME_DOS}. Mirror resolve_workspace_root Path(...).resolve() discipline. Where it lives (config.py).`,
      '2. The DOS_HOME directory tree: config.toml, projects/index.jsonl, decisions.jsonl. Exact JSONL row schema for each (field names, types). projects row: project_id, path, taxonomy, reasons_declared, first_seen_ms, last_run, run/wedge/refusal counts. decisions row: project_id, reason_token, resolver_kind, lane, resolved_how, ts_ms.',
      '3. project_id derivation MUST be deterministic and stable across runs (no random). Propose: short hash (which algo? sha256 truncated, hex) of the realpath. It is path-derived so needs no clock.',
      '4. The append discipline for the central JSONL: reuse lane_journal O_APPEND+fsync+torn-tail-tolerant pattern, or simpler? Argue. These are cross-process (many dos invocations append concurrently).',
      '5. Whether DOS_HOME paths belong on PathLayout (per-workspace) or a SEPARATE object (machine-global). PathLayout is per-root; DOS_HOME is per-machine. Propose where dos_home lives on the config so callers reach it cleanly.',
      'Return a precise spec.',
    ].join('\n'),
  },
  {
    key: 'ensure',
    label: 'probe:ensure-create',
    prompt: [
      COMMON, '',
      'DESIGN PROBE — ensure_project_home + auto-create-on-first-write semantics.',
      'Read every CLI subcommand in cli.py and classify each as READ-ONLY (must never write) or PERSISTING. Read lane_journal.append (it does p.parent.mkdir already), archive_lock._write_lock (mkdir already), run_id.write_run_json (mkdir already).',
      'Produce:',
      '1. The exact classification table: subcommand -> read-only|persisting, with justification. verify/man/doctor/decisions = read-only. arbitrate-taking-a-lease/journal-append/run-id-mint-writing-run.json/lease-acquire = persisting.',
      '2. ensure_project_home(cfg) exact behavior: idempotent. Creates .dos/ + writes .dos/.gitignore (give EXACT content) + writes/updates .dos/project.json + appends/updates the projects/index.jsonl row. Emits ONE stderr courtesy line the FIRST time only (detect first-time how — .dos/ absent before this call?).',
      '3. WHERE the ensure hook fires. Options: (a) inside each persisting kernel fn, (b) in cli.py before dispatching a persisting subcommand, (c) a decorator. The kernel fns already mkdir their own parent — does ensure_project_home REPLACE those scattered mkdirs or wrap them? RESOLVE the import-cycle risk: home imports config; if lane_journal imports home and home imports lane_journal that is a cycle. Propose the acyclic arrangement (hint: the CLI layer can call ensure before dispatch, keeping kernel fns ignorant of home).',
      '4. The safety property: "dos verify" / "dos man" in a foreign read-only repo writes NOTHING (no .dos/, no ~/.dos row). PROVE the design guarantees it.',
      'Return a precise spec.',
    ].join('\n'),
  },
  {
    key: 'backflow',
    label: 'probe:backflow-reindex',
    prompt: [
      COMMON, '',
      'DESIGN PROBE — the projection back-flow + dos reindex + cross-project learning.',
      'Read decisions.py FULLY (the model: read-only projection over 4 sources, stores nothing of its own, collect_decisions, _resolver_for, ResolverKind ORACLE/JUDGE/HUMAN). Read picker_oracle.py oracle_disagrees concept.',
      'Produce:',
      '1. The projection-not-sync contract for ~/.dos: per-project .dos/ is authoritative; ~/.dos is a rebuildable digest. "dos reindex" walks every known .dos/project.json (how does reindex KNOW every project? projects/index.jsonl is the registry of known paths — reindex reads it for the path list, re-stats each .dos/; if a project dir moved/deleted mark stale, do not crash). Specify reindex algorithm.',
      '2. WHEN does a decisions.jsonl row get appended? A decision is RESOLVED (operator forced a lane / judge cleared a wedge / soak closed). decisions.py is read-only and the CLI is one-shot — no resolve event exists today. Propose the minimal resolution-capture: does "dos arbitrate --force" append a resolved-decision row? Does "dos judge" when it rules? Be concrete about which existing actions become capture points, WITHOUT turning decisions.py into a store (the row is written by home.py/the CLI action, not by the projection).',
      '3. The cross-project QUERIES this enables, as concrete dos commands + the aggregate: which-repos-wedge-most (group decisions.jsonl by project_id, count WEDGE), which-lanes-refuse-everywhere (group by lane across ARBITER_REFUSE), oracle-miscalibration (across projects, % of oracle_disagrees decisions force-overridden -> JUDGE-tier calibration). Give the exact "dos projects" / "dos learn" subcommand surface.',
      '4. How this ties to the hackability goal (reasons-as-data) and the resolver-kind axis already in decisions.py — the aggregate is DATA that informs tuning, never monkeypatching.',
      'Return a precise spec, explicitly bounding v1 (index exists + populated) vs v2 (queries + learning).',
    ].join('\n'),
  },
  {
    key: 'migration',
    label: 'probe:migration-compat',
    prompt: [
      COMMON, '',
      'DESIGN PROBE — migration, back-compat, and the test surface.',
      'Read ALL tests in tests/ (test_arbiter, test_oracle_and_loop, test_decisions, test_judge, test_refusal_and_tokens, test_verify_no_plan). Identify every test that depends on a PathLayout field location or sets a DISPATCH_*_PATH env override. Read .gitignore.',
      'Produce:',
      '1. Which existing tests would BREAK if default_config() switches to for_dos_dir, and exactly why. (Do any tests construct default_config and assert a path under docs/? Do any rely on archive_lock/lane_journal default paths?) For each, the minimal fix.',
      '2. The new test files + cases, matching existing style: test_state_home.py (for_dos_dir field mapping, resolve_dos_home precedence incl win32/XDG/HOME branches via monkeypatched env, project_id determinism), test_ensure_home.py (auto-create on first write, read-only writes nothing, idempotency, gitignore content, courtesy-line-once), test_central_index.py (projects row append, decisions row append, reindex rebuilds from project.json, stale-project handling, concurrent-append torn-tail tolerance).',
      '3. The .gitignore delta for the dos REPO ITSELF (currently ignores .dos-workspace/; should it also ignore .dos/ so dos-operating-on-its-own-repo during tests does not dirty git?). And the shipped .dos/.gitignore template content.',
      '4. job-side impact: confirm by reading CLAUDE.md "How job consumes it" that NOTHING here touches the job shims (they re-export dos.*; job_config stays for_root). State the one-line proof.',
      '5. Migration note: existing job repos have state under docs/_fanout_runs etc. This change does NOT migrate them (job stays for_root). For a NEW generic workspace there is nothing to migrate. Is there ANY existing dos-generic-default user whose state moves? Confirm.',
      'Return a precise spec.',
    ].join('\n'),
  },
]

const probes = await parallel(PROBES.map(p => () =>
  agent(p.prompt, { label: p.label, phase: 'Probe' }).then(text => ({ key: p.key, text }))
))
const probeResults = probes.filter(Boolean)
log(`${probeResults.length}/${PROBES.length} design probes returned`)

phase('Critique')

const probeDigest = probeResults.map(p => `\n===== PROBE: ${p.key} =====\n${p.text}`).join('\n')

const CRITIC_SCHEMA = {
  type: 'object',
  properties: {
    breakages: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          law_violated: { type: 'string' },
          where: { type: 'string' },
          why: { type: 'string' },
          fix: { type: 'string' },
          severity: { type: 'string', enum: ['blocker', 'major', 'minor'] },
        },
        required: ['title', 'law_violated', 'why', 'fix', 'severity'],
      },
    },
    unresolved_decisions: { type: 'array', items: { type: 'string' } },
    verdict: { type: 'string', enum: ['design-sound', 'needs-fixes', 'has-blockers'] },
  },
  required: ['breakages', 'unresolved_decisions', 'verdict'],
}

const CRITIC_LENSES = [
  { lens: 'job-and-seam', focus: 'Does the design move job, break the byte-thin shims, or falsely claim the seam already routes every path? VERIFY the seam claim by grepping the actual consumers of paths.* — list any that do NOT go through config so the PathLayout swap would miss them.' },
  { lens: 'layering-and-cycles', focus: 'Does home.py importing config plus a kernel module importing home create an import cycle? Does the design turn decisions.py into a store? Does any src/dos/ non-driver module end up naming a host? Trace the actual import graph.' },
  { lens: 'safety-and-determinism', focus: 'Can a read-only syscall in a foreign repo write anything (a .dos/ dir, a ~/.dos row, a courtesy line that is actually a write)? Is project_id deterministic? Do central-index appends follow the fsync/torn-tail discipline and are they safe under concurrent dos invocations? Any wall-clock/random in a reproducible path?' },
]

const critics = await parallel(CRITIC_LENSES.map(c => () =>
  agent([
    COMMON, '',
    `You are an ADVERSARIAL design critic, lens = "${c.lens}". Find where this proposed design BREAKS a hard constraint or design law. Default to skepticism — assume the probes were optimistic. ${c.focus}`,
    '', 'Here are the design probes to critique:', probeDigest, '',
    'Read the actual code to confirm each breakage is real (not hypothetical). Only report a breakage you can point to a file/function for. Return structured findings.',
  ].join('\n'), { label: `critic:${c.lens}`, phase: 'Critique', schema: CRITIC_SCHEMA })
))
const critiqueResults = critics.filter(Boolean)
const allBreakages = critiqueResults.flatMap(c => c.breakages || [])
const blockers = allBreakages.filter(b => b.severity === 'blocker')
log(`critique: ${allBreakages.length} findings (${blockers.length} blockers); verdicts ${critiqueResults.map(c => c.verdict).join(', ')}`)

phase('Synthesize')

const synthesis = await agent([
  COMMON, '',
  'You are the lead architect. Synthesize the design probes AND the adversarial critique into ONE coherent, build-ready design for the .dos/ + DOS_HOME state-home feature. Resolve every blocker and major finding by ADOPTING its fix. Where probes contradicted, pick the option that best honors the hard constraints and say why.',
  '', '=== PROBES ===', probeDigest, '',
  '=== CRITIQUE FINDINGS (JSON) ===', JSON.stringify({ breakages: allBreakages, unresolved: critiqueResults.flatMap(c => c.unresolved_decisions || []) }, null, 2),
  '',
  'Produce a complete design with these sections, concrete enough that a builder implements without re-deciding:',
  '1. THE GAP THIS CLOSES (2-3 paras, in the voice of docs/70 & docs/71 — reference the inherited job docs/ layout and the seam).',
  '2. DESIGN LAWS THIS MUST HONOR (the hard constraints, each with the specific way this design satisfies it).',
  '3. NORTH-STAR ACCEPTANCE (a runnable snippet: dos verify in a foreign repo writes nothing; dos arbitrate auto-creates .dos/; a second project; dos projects shows both; dos reindex rebuilds).',
  '4. THE FULL FIELD MAPPING (for_root field -> for_dos_dir location), with the execution_state/plans_glob STAY-repo-relative decision resolved and justified.',
  '5. DOS_HOME resolution + central store schemas (projects row, decisions row, project.json) — exact field lists.',
  '6. ensure_project_home semantics + the acyclic import arrangement + the read-only-writes-nothing proof.',
  '7. PHASE BREAKDOWN: v1 = Phase 1 (for_dos_dir + resolve_dos_home) + Phase 2 (home.py ensure + auto-create), v2 = Phase 3 (central indices populated) + Phase 4 (reindex + cross-project queries + doctor/HACKING). For EACH phase: the slices (1a/1b/1c style) and the per-phase litmus tests (named test cases, matching tests/ style).',
  '8. OUT OF SCOPE (explicit, like docs/70 & 71).',
  '9. The exact .dos/.gitignore template content, and whether the dos repo own .gitignore needs a .dos/ line.',
  '',
  'Write it as the BODY of a plan doc (markdown). Do not write the status-header frontmatter — I will add it. Be exhaustive and precise; this is the contract the whole build executes against.',
].join('\n'), { label: 'synthesize:design', phase: 'Synthesize' })

return {
  probeCount: probeResults.length,
  critique: { findings: allBreakages, blockers: blockers.length, verdicts: critiqueResults.map(c => c.verdict) },
  design: synthesis,
}

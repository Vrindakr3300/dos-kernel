"""Corpus loader — parse the CC trajectory `.jsonl` files into structured Session
objects ONCE, so each track is a thin labeling function over the result.

The gold for every track is authored by something other than the session being
judged. This module only *extracts* the raw, unforgeable facts (timestamps,
path-sets, tool results, lineage) — it makes no verdicts. The tracks make the
verdicts; the kernel scores them.

Nothing here imports `dos`; it is pure corpus I/O + dataclasses. The tracks pull
in the kernel.
"""
from __future__ import annotations

import collections
import datetime
import glob
import hashlib
import json
import os
import re
from dataclasses import dataclass, field

# The corpus location — where the Claude Code session `.jsonl` logs live. CC names
# each project dir by ENCODING the workspace's absolute path: every separator (the
# drive colon, `\`, `/`) becomes a single dash, runs NOT collapsed — <workspace-abspath>
# -> the dashed slug. So the default is DERIVED from the current workspace's abspath
# the same way (portable: it computes the right dir on any machine/clone, names no
# hardcoded path), and is override-able with DOS_TRAJECTORY_CORPUS for a second
# workspace's corpus.
def _cc_project_dir(workspace_abspath: str) -> str:
    """Encode an absolute workspace path into its `~/.claude/projects/<enc>` dir
    name the way Claude Code does: each of `: \\ /` -> a single `-`."""
    enc = re.sub(r"[:\\/]", "-", workspace_abspath)
    return os.path.expanduser(os.path.join("~", ".claude", "projects", enc))


DEFAULT_CORPUS = os.environ.get("DOS_TRAJECTORY_CORPUS") or _cc_project_dir(
    os.path.abspath(os.environ.get("DOS_WORKSPACE", os.getcwd()))
)

# The basename of the repo tree we judge — the single path COMPONENT that marks
# "inside this repo". A session may also edit sibling repos whose directory name
# merely STARTS WITH this token (../dos-concept-video, ../dos-strategy, ../dos-mcp
# as a SEPARATE checkout); those are NOT in the tree and must be excluded from
# Track A's region intersection. Configurable so the benchmark is portable to any
# clone location (it does not assume the author's `…/work/dos` layout): override
# with the DOS_TREE_ROOT env var, default the neutral basename "dos".
DOS_TREE_ROOT = os.environ.get("DOS_TREE_ROOT", "dos")


def parse_ts(t) -> datetime.datetime | None:
    """ISO-8601 (with trailing Z) -> aware datetime, or None."""
    if not t:
        return None
    try:
        return datetime.datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    except Exception:
        return None


def _norm(path: str) -> str:
    """Normalize a tool-use file_path to a forward-slash, lowercased key for
    cross-platform intersection. Absolute Windows paths and `..`-relative paths
    both appear in the corpus."""
    if not path:
        return ""
    return os.path.normpath(path).replace("\\", "/").lower()


def in_dos_tree(norm_path: str, tree_root: str | None = None) -> bool:
    """Is this normalized path inside THIS repo's tree (not a sibling repo)?

    The decision is whether `tree_root` (default `DOS_TREE_ROOT`, from the env or
    the neutral "dos") appears as a full path COMPONENT — i.e. `/<root>` followed
    by a `/` or the end of string. The component boundary is what rejects sibling
    repos whose directory name merely STARTS WITH the root: `…/dos/…` is in-tree,
    but `…/dos-concept-video/…` / `…/dos-strategy/…` are NOT (the next char is a
    `-`, not a `/`). A nested `…/dos/src/dos_mcp/…` IS in-tree (the first `/dos`
    component matches before the `dos_mcp` leaf). `norm_path` is already
    forward-slash + lowercased by `_norm`."""
    root = (tree_root if tree_root is not None else DOS_TREE_ROOT).replace("\\", "/").lower()
    if not root:
        return False
    # Anchor on a path-component boundary on the LEFT (`/<root>`) and require a
    # boundary on the RIGHT (`/` or end). Scan every occurrence so a real
    # `/<root>/` later in the path still counts even if an earlier component is a
    # sibling-prefix (`/dos-strategy/dos/…`). This is the byte-faithful
    # generalization of the old `work/dos` needle + boundary check, just sourced
    # from a configurable basename instead of the author's machine layout.
    needle = "/" + root
    start = 0
    while True:
        idx = norm_path.find(needle, start)
        if idx < 0:
            return False
        after = norm_path[idx + len(needle):]
        if after[:1] in ("", "/"):  # `/<root>` is a full component
            return True
        start = idx + 1  # this was a longer dir name (e.g. `/dos-strategy`); keep scanning


@dataclass
class Mutation:
    """One Edit/Write tool call — the *act*, separated from narration."""

    ts: datetime.datetime
    tool: str  # Edit | Write | NotebookEdit | MultiEdit
    path: str  # normalized
    in_tree: bool  # is it inside THIS repo


@dataclass
class ToolEvent:
    """One tool_use + its paired tool_result (if found), for the trajectory-shape
    tracks (C/E)."""

    ts: datetime.datetime
    name: str
    tool_use_id: str
    input_repr: str  # a short, redaction-safe signature of the input (NOT raw content)
    is_error: bool | None = None  # filled from the paired tool_result
    result_excerpt: str = ""  # short excerpt of the result, error text only
    result_digest: str = ""  # sha1 of the WHOLE result bytes (redaction-safe) — the
    #                          tool_stream.StreamStep datum for Track E's repeat/stall verdict


@dataclass
class Claim:
    """A natural-language self-report span in an assistant turn — the FORGEABLE
    thing a downstream byte must witness (Tracks B/D)."""

    ts: datetime.datetime
    turn_uuid: str
    kind: str  # verified | done | tests_pass | shipped | committed
    span: str  # the matched sentence (redaction-safe excerpt)


@dataclass
class Session:
    sid: str  # sessionId
    path_file: str  # the .jsonl basename
    branch: str | None
    cwd: str | None
    start: datetime.datetime | None
    end: datetime.datetime | None
    nass: int  # assistant turns
    sidechain: bool
    mutations: list[Mutation] = field(default_factory=list)
    tool_events: list[ToolEvent] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    # parentUuid lineage: the set of parent uuids referenced (cross-session join
    # for Track D is by sessionId continuity + the last-prompt summary, since
    # parentUuid is intra-session; see track_d).
    first_uuid: str | None = None
    summary_text: str = ""  # the ai-title / last-prompt, the handoff surface

    @property
    def tree_mutations(self) -> list[Mutation]:
        return [m for m in self.mutations if m.in_tree]

    @property
    def edited_paths(self) -> set[str]:
        return {m.path for m in self.tree_mutations}

    def edit_window(self, path: str) -> tuple[datetime.datetime, datetime.datetime] | None:
        """First and last time THIS session wrote `path` (its uncommitted-risk
        window for that region)."""
        times = [m.ts for m in self.tree_mutations if m.path == path]
        if not times:
            return None
        return (min(times), max(times))

    def overlaps(self, other: "Session") -> bool:
        if not (self.start and self.end and other.start and other.end):
            return False
        return self.start < other.end and other.start < self.end


# Closed claim vocabulary — AGENTIVE, first-person, COMPLETED-action regexes.
#
# The hard lesson (measured): a loose word-match (`"committed"`) mines PROSE for
# phantom claims — 2415/2597 "committed" hits were the ADJECTIVE ("a committed
# phased plan", "the committed tree", "uncommitted changes"), not a self-report
# "I committed X". So we require the COMPLETED FIRST-PERSON form and exclude the
# negated/adjectival/intent uses. This is the same discipline as
# plan_source._looks_like_phase_id: UNDER-harvest a prose dialect rather than mint
# phantom claims (docs/243 caveat #5 — the value density is lower when honest).
#
# Each kind is (positive_regex, negative_regex|None): a span matches the kind iff
# positive fires AND negative does NOT.
_CLAIM_REGEX = {
    # "I verified ...", "I've confirmed ...", "I've checked that ..." — a
    # first-person completed verification act. Excludes "let me verify" (intent)
    # and "to verify" (purpose).
    "verified": (
        re.compile(r"\bi(?:'ve| have)?\s+(?:verified|confirmed|double-checked)\b", re.I),
        re.compile(r"\b(?:let me|to|will|need to|should|can|want to)\s+(?:verify|confirm)\b", re.I),
    ),
    # "tests pass", "the suite is green", "all N tests pass" — but NOT
    # "let me check the tests pass", "to make tests pass", "make the tests pass",
    # "do the tests pass?" (those are intent/question, not assertion).
    "tests_pass": (
        re.compile(r"\b(?:all\s+\d+\s+|the\s+)?tests?\s+pass(?:es|ing)?\b"
                   r"|\bsuite\s+is\s+green\b|\btests?\s+are\s+green\b|\btest\s+suite\s+passes\b", re.I),
        re.compile(r"\b(?:let me|to|make|do|will|whether|if|see if|check (?:that|if|whether))\b[^.]*\btests?\b", re.I),
    ),
    # "this is done", "I've completed X", "I finished X" — completed first-person.
    # Excludes "to be done", "needs to be done", "not done", "almost done".
    "done": (
        re.compile(r"\bthis is done\b|\bit'?s done\b|\bi(?:'ve| have)?\s+(?:completed|finished)\b"
                   r"|\bnow complete\b", re.I),
        re.compile(r"\b(?:not|isn'?t|aren'?t|to be|needs? to be|almost|nearly|once|after|when|before)\b[^.]*\bdone\b", re.I),
    ),
    # "X is shipped", "I shipped X", "now ships" — completed ship. Excludes
    # "to ship", "will ship", "not shipped", "not yet shipped".
    "shipped": (
        re.compile(r"\bis shipped\b|\bi shipped\b|\bhas shipped\b|\bnow ships\b|\bshipped (?:the|it|in)\b", re.I),
        re.compile(r"\b(?:not|isn'?t|to|will|yet|never)\s+ship|\bnot\b[^.]*\bshipped\b", re.I),
    ),
    # "I committed X", "I just committed", "commit landed", "now committed to git"
    # — a first-person commit ANNOUNCEMENT. Excludes the adjective: "a committed
    # plan", "the committed tree", "uncommitted", "committed to the idea/approach".
    "committed": (
        re.compile(r"\bi(?:'ve| have)?\s+(?:just\s+)?committed\b|\bcommit landed\b"
                   r"|\bnow committed\b|\bcommitted (?:it|them|the (?:fix|change|work|file|doc|source|test))\b", re.I),
        re.compile(r"\bun-?committed\b|\bcommitted (?:phased|plan|to the|approach|idea|design|direction)\b"
                   r"|\b(?:not|isn'?t|aren'?t|hasn'?t|haven'?t|yet)\b[^.]*\bcommitted\b"
                   # third-party subject — a CONCURRENT agent's commit, not the
                   # claimant's own act, so the claimant's next commit is not its witness.
                   r"|\b(?:concurrent|automation|scheduled|another|other|someone|agent|they|it)\b[^.]*\bcommitted\b", re.I),
    ),
}


def _extract_claims(text: str, ts, turn_uuid) -> list[Claim]:
    if not text:
        return []
    out = []
    for kind, (pos, neg) in _CLAIM_REGEX.items():
        m = pos.search(text)
        if not m:
            continue
        # grab the surrounding sentence as a redaction-safe excerpt
        idx = m.start()
        start = text.rfind(".", 0, idx) + 1
        stop = text.find(".", idx)
        stop = stop if stop > 0 else min(len(text), idx + 140)
        span = text[start:stop].strip()[:200]
        # negation/adjectival guard runs on the SENTENCE, not the whole turn
        if neg is not None and neg.search(span):
            continue
        out.append(Claim(ts=ts, turn_uuid=turn_uuid, kind=kind, span=span))
    return out


def _input_signature(name: str, inp: dict) -> str:
    """A short, redaction-SAFE signature of a tool input — never the raw content,
    but UNIQUE to the whole call so two different commands don't collide.

    The hard lesson (measured): keeping only the FIRST LINE of a shell command made
    every multi-line command that shared a `$env:PYTHONPATH = ...` / `cd ...` setup
    prefix look IDENTICAL — a false thrash signature. So we sign the WHOLE
    normalized command via a short hash, plus a readable head for display."""
    if not isinstance(inp, dict):
        return ""
    if name in ("Bash", "PowerShell"):
        cmd = " ".join(str(inp.get("command", "")).split())  # collapse whitespace/newlines
        if not cmd:
            return name
        head = cmd[:60]
        h = hashlib.sha1(cmd.encode("utf-8", "replace")).hexdigest()[:8]
        return f"{head}#{h}"
    if name in ("Edit", "Write", "Read", "NotebookEdit", "MultiEdit"):
        return _norm(str(inp.get("file_path", "")))
    if name == "Grep":
        return f"grep:{str(inp.get('pattern',''))[:40]}"
    if name == "Glob":
        return f"glob:{str(inp.get('pattern',''))[:40]}"
    return name


def load_session(path: str) -> Session | None:
    """Parse one .jsonl into a Session. Two-pass: first collect records, then pair
    tool_use with tool_result by toolUseID."""
    branch = cwd = sid = first_uuid = None
    ts_list: list[str] = []
    nass = 0
    sidechain = False
    mutations: list[Mutation] = []
    tool_events: list[ToolEvent] = []
    claims: list[Claim] = []
    summary_text = ""
    # map toolUseID -> ToolEvent so we can backfill the result
    by_id: dict[str, ToolEvent] = {}

    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            rtype = r.get("type")
            if r.get("gitBranch") and branch is None:
                branch = r.get("gitBranch")
            if r.get("cwd") and cwd is None:
                cwd = r.get("cwd")
            if r.get("sessionId") and sid is None:
                sid = r.get("sessionId")
            if r.get("uuid") and first_uuid is None:
                first_uuid = r.get("uuid")
            if r.get("isSidechain"):
                sidechain = True
            t = r.get("timestamp")
            if t:
                ts_list.append(t)
            tparsed = parse_ts(t)

            if rtype in ("ai-title", "last-prompt"):
                # the handoff surface — what a peer session would read as the summary
                msg = r.get("message") or r.get("title") or r.get("prompt") or ""
                if isinstance(msg, str):
                    summary_text = (summary_text + " " + msg).strip()[:1000]

            if rtype == "assistant":
                nass += 1
                msg = r.get("message", {})
                turn_uuid = r.get("uuid", "")
                if isinstance(msg, dict):
                    for b in (msg.get("content") or []):
                        if not isinstance(b, dict):
                            continue
                        bt = b.get("type")
                        if bt == "text" and tparsed:
                            claims.extend(_extract_claims(b.get("text", ""), tparsed, turn_uuid))
                        elif bt == "tool_use":
                            nm = b.get("name", "?")
                            inp = b.get("input", {}) or {}
                            tuid = b.get("id", "")
                            if tparsed:
                                ev = ToolEvent(
                                    ts=tparsed, name=nm, tool_use_id=tuid,
                                    input_repr=_input_signature(nm, inp),
                                )
                                tool_events.append(ev)
                                if tuid:
                                    by_id[tuid] = ev
                                if nm in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
                                    p = _norm(str(inp.get("file_path", "")))
                                    if p:
                                        mutations.append(
                                            Mutation(ts=tparsed, tool=nm, path=p, in_tree=in_dos_tree(p))
                                        )

            if rtype == "user":
                # tool_result records arrive as user-role messages with a
                # tool_result content block carrying the toolUseID.
                msg = r.get("message", {})
                if isinstance(msg, dict):
                    for b in (msg.get("content") or []):
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            tuid = b.get("tool_use_id", "")
                            ev = by_id.get(tuid)
                            if ev is not None:
                                ev.is_error = bool(b.get("is_error"))
                                content = b.get("content", "")
                                if isinstance(content, list):
                                    content = " ".join(
                                        c.get("text", "") for c in content if isinstance(c, dict)
                                    )
                                txt = str(content)
                                # digest the WHOLE result bytes (redaction-safe) so
                                # Track E can detect a repeat/stall loop via the
                                # kernel's tool_stream verdict — same args + same
                                # result digest repeated = a no-progress read-loop.
                                ev.result_digest = hashlib.sha1(txt.encode("utf-8", "replace")).hexdigest()[:12]
                                if ev.is_error:
                                    ev.result_excerpt = txt[:240]
    except Exception:
        return None

    if not ts_list:
        return None
    ts_list.sort()
    return Session(
        sid=sid or os.path.basename(path),
        path_file=os.path.basename(path),
        branch=branch,
        cwd=cwd,
        start=parse_ts(ts_list[0]),
        end=parse_ts(ts_list[-1]),
        nass=nass,
        sidechain=sidechain,
        mutations=mutations,
        tool_events=tool_events,
        claims=claims,
        first_uuid=first_uuid,
        summary_text=summary_text,
    )


def load_corpus(
    corpus_dir: str = DEFAULT_CORPUS,
    *,
    min_assistant_turns: int = 3,
    dos_only: bool = True,
    exclude_sids: set[str] | None = None,
    before: datetime.datetime | None = None,
) -> list[Session]:
    """Load every substantial dos-repo session.

    exclude_sids: self-witness guard — drop these session ids (e.g. the session
    currently doing the analysis must not appear in its own benchmark — docs/243
    caveat #1).

    before: FREEZE the corpus at a cutoff — drop any session that STARTED at or
    after this instant. The CC corpus is NON-STATIONARY (it grows as sessions run,
    including the analyzing session itself), so a reproducible benchmark must pin a
    snapshot boundary. Without it, two runs minutes apart give different n (docs/243
    caveat #3: state the n and the scope on every number).
    """
    exclude_sids = exclude_sids or set()
    out: list[Session] = []
    for f in sorted(glob.glob(os.path.join(corpus_dir, "*.jsonl"))):
        s = load_session(f)
        if s is None:
            continue
        if s.sid in exclude_sids:
            continue
        if before is not None and s.start is not None and s.start >= before:
            continue
        if s.nass < min_assistant_turns or s.sidechain:
            continue
        if dos_only and not in_dos_tree(_norm(s.cwd or "")):
            # the session's working dir must be inside THIS repo's tree (same
            # component test as a mutation path — a sibling-prefix cwd is excluded)
            continue
        out.append(s)
    out.sort(key=lambda s: (s.start or datetime.datetime.max.replace(tzinfo=datetime.timezone.utc)))
    return out


def detect_self_sid(corpus_dir: str = DEFAULT_CORPUS) -> str | None:
    """Best-effort: the sessionId of the CURRENTLY-RUNNING (this) session — the
    most-recently-modified .jsonl whose last record is within the last few minutes.
    Used to auto-populate the self-witness exclusion so the analysis never grades
    itself. Returns None if undetectable (then the caller should pass an explicit
    --exclude-sid or a --before cutoff)."""
    files = glob.glob(os.path.join(corpus_dir, "*.jsonl"))
    if not files:
        return None
    newest = max(files, key=os.path.getmtime)
    s = load_session(newest)
    return s.sid if s else None


def peak_concurrency(sessions: list[Session]) -> int:
    """Sweep-line max simultaneous sessions — the headline `19`/`20` number."""
    events = []
    for s in sessions:
        if s.start and s.end:
            events.append((s.start, 1))
            events.append((s.end, -1))
    events.sort(key=lambda x: (x[0], x[1]))
    cur = mx = 0
    for _, d in events:
        cur += d
        mx = max(mx, cur)
    return mx

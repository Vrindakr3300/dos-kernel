package hook

// claim_extract — the Go port of dos.claim_extract (docs/134 §2.1, docs/125 GHF
// native stop). What (plan, phase) did an agent CLAIM it shipped? The Stop hook is
// handed a transcript; the truth syscall (verify) wants (plan, phase). This is the
// bridge — it reads what an agent ASSERTED, so the hook can check each assertion
// against git. It verifies NOTHING; it only extracts the claims (the oracle verifies).
//
// Three rungs, strongest-first (mirroring the oracle's evidence ladder):
//
//  1. MARKER (strongest, opt-in): a line `DOS-CLAIM: <plan> <phase>`. Byte-exact.
//  2. FRONTMATTER (structural): a skill declared dos.plan/dos.phase — passed in.
//  3. HEURISTIC (weakest, ABSTAINING): a `shipped/landed/done <ID>` sentence with an
//     explicit phase-SHAPED token. Only fires on an ID-shaped token; never invents.
//
// The load-bearing rule, ported verbatim: ABSTAIN, never invent. Free prose yields
// NO claim. All three regexes are RE2-compatible (no lookbehind), so the Go regexp
// package reproduces the Python `re` matches byte-for-byte on these patterns.

import (
	"encoding/json"
	"os"
	"regexp"
	"strings"
)

// _markerRE — the byte-exact DOS-CLAIM marker, anchored at a line start (after
// optional list/quote markup) so a mention INSIDE prose ("emit a DOS-CLAIM: line")
// is not mistaken for a real one. Port of claim_extract._MARKER_RE
// (re.VERBOSE | re.MULTILINE). The verbose pattern is inlined to its literal form:
//
//	^[ \t>*\-]* DOS-CLAIM:[ \t]+ (\S+) [ \t]+ (\S+) [ \t]*$
//
// `(?m)` gives MULTILINE (^/$ match at line boundaries). Go's regexp `$` matches at
// end-of-text or before a final `\n` in multiline mode — the same as Python's `re`
// `$` under re.MULTILINE (matches before each `\n`), so the per-line anchoring agrees.
var _markerRE = regexp.MustCompile(`(?m)^[ \t>*\-]*DOS-CLAIM:[ \t]+(\S+)[ \t]+(\S+)[ \t]*$`)

// _phaseTokenRE — a plan/phase-shaped id for the HEURISTIC rung: an uppercase-led
// token of LETTERS then DIGITS (AUTH2, FQ390, DLA3). Port of _PHASE_TOKEN_RE:
// `\b([A-Z][A-Z_]*[A-Z])(\d+)\b`. Group 1 is the letter stem (the plan), group 0 is
// the full token (the phase). Deliberately narrow — misses lowercased/prose-only
// claims (safe: abstain) rather than guess.
var _phaseTokenRE = regexp.MustCompile(`\b([A-Z][A-Z_]*[A-Z])(\d+)\b`)

// _completionHintRE — the completion verbs gating the heuristic rung. Port of
// _COMPLETION_HINT_RE: `\b(shipped|landed|completed|finished|done|merged)\b` (i).
var _completionHintRE = regexp.MustCompile(`(?i)\b(shipped|landed|completed|finished|done|merged)\b`)

// Claim is one (plan, phase) an agent claimed shipped, plus how we know. `rung` is
// marker › frontmatter › heuristic (strongest-first). `confident` is true only for
// the marker/frontmatter rungs (the Python @property), so the dispatcher can act on
// a confident claim and treat a heuristic one as advisory unless --strict.
type Claim struct {
	Plan  string
	Phase string
	Rung  string
	Raw   string
}

// Confident mirrors claim_extract.Claim.confident: marker/frontmatter are confident.
func (c Claim) Confident() bool { return c.Rung == "marker" || c.Rung == "frontmatter" }

// claimFromFrontmatter — the FRONTMATTER rung: a skill declared (dos.plan, dos.phase).
// Port of claim_extract.claim_from_frontmatter. Returns one claim when both present,
// else nil. Pure — the hook reads the frontmatter at the boundary, passes two strings.
func claimFromFrontmatter(plan, phase string) []Claim {
	plan = strings.TrimSpace(plan)
	phase = strings.TrimSpace(phase)
	if plan != "" && phase != "" {
		return []Claim{{Plan: plan, Phase: phase, Rung: "frontmatter",
			Raw: "dos.plan=" + plan + " dos.phase=" + phase}}
	}
	return nil
}

// extractClaims — the PURE extractor (port of claim_extract.extract_claims). Claims
// an agent asserted, strongest rung first. Deduplicates on (plan, phase) keeping the
// strongest rung. allowHeuristic=false restricts to the byte-exact MARKER rung (the
// fail-closed posture). Returns nil when nothing is confidently extractable.
//
// Iteration order discipline: the Python builds an insertion-ordered dict and returns
// list(out.values()); the Go dispatcher does not depend on claim order (it verifies
// each and blocks on ANY confident failure), but to keep a deterministic, Python-
// faithful order we preserve marker-then-heuristic insertion order via a key slice.
func extractClaims(text string, allowHeuristic bool) []Claim {
	if text == "" {
		return nil
	}
	out := map[claimKey]Claim{}
	var order []claimKey

	// Rung 1 — the byte-exact marker. Strongest; always honored.
	for _, m := range _markerRE.FindAllStringSubmatch(text, -1) {
		plan, phase := m[1], m[2]
		k := claimKey{plan, phase}
		if _, seen := out[k]; !seen {
			order = append(order, k)
		}
		// Match Python: out[(plan,phase)] = Claim(...) — a later marker line for the
		// same (plan,phase) overwrites raw but keeps one entry. raw is the stripped
		// matched line.
		out[k] = Claim{Plan: plan, Phase: phase, Rung: "marker", Raw: strings.TrimSpace(m[0])}
	}

	if !allowHeuristic {
		return claimsInOrder(out, order)
	}

	// Rung 3 — the abstaining heuristic. Only fires when a phase-SHAPED token sits in
	// a line that also carries a completion verb. Never invents an id from prose. A
	// token already captured by the marker rung is not downgraded.
	for _, line := range splitLines(text) {
		if !_completionHintRE.MatchString(line) {
			continue
		}
		for _, tok := range _phaseTokenRE.FindAllStringSubmatch(line, -1) {
			phase := tok[0] // e.g. "AUTH2"
			plan := tok[1]  // the letter stem, e.g. "AUTH"
			k := claimKey{plan, phase}
			if _, exists := out[k]; exists {
				continue // don't shadow a stronger rung
			}
			out[k] = Claim{Plan: plan, Phase: phase, Rung: "heuristic", Raw: strings.TrimSpace(line)}
			order = append(order, k)
		}
	}
	return claimsInOrder(out, order)
}

// claimKey is the (plan, phase) dedup key, mirroring the Python dict's tuple key.
type claimKey struct{ plan, phase string }

func claimsInOrder(out map[claimKey]Claim, order []claimKey) []Claim {
	res := make([]Claim, 0, len(order))
	for _, k := range order {
		res = append(res, out[k])
	}
	return res
}

// splitLines mirrors Python str.splitlines() closely enough for this use: split on
// \n after normalizing \r\n and bare \r. Python's splitlines also splits on a few
// exotic separators (\v, \f, \x1c…), but a transcript's assistant text is \n/\r\n
// only, and the completion-hint scan is line-local, so \n/\r normalization matches.
func splitLines(s string) []string {
	s = strings.ReplaceAll(s, "\r\n", "\n")
	s = strings.ReplaceAll(s, "\r", "\n")
	return strings.Split(s, "\n")
}

// ---------------------------------------------------------------------------
// Boundary I/O — the transcript reader. Port of assistant_text_from_transcript.
// NOT pure (reads a file). Mirrors scripts/trajectory_audit.py's block convention
// so the two readers can't drift.
// ---------------------------------------------------------------------------

// assistantTextFromTranscript reads the text of the last N assistant turn(s) from a
// transcript JSONL. The Stop hook verifies "what the agent just claimed," so we read
// the TAIL — the final assistant turn(s) — not the whole session. Returns "" on any
// read/parse failure (the no-crash floor: a missing/garbled transcript yields no
// claims, the agent stops unverified — the safe direction). Port of
// claim_extract.assistant_text_from_transcript.
func assistantTextFromTranscript(path string, lastTurns int) string {
	if lastTurns < 1 {
		lastTurns = 1
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	// Python reads with errors="replace"; Go's []byte->string of invalid UTF-8 keeps
	// the bytes (the JSON parse below tolerates them line-by-line). Split on raw \n
	// (readlines keeps line content; we strip each line before json.Unmarshal).
	var turns []string
	for _, raw := range strings.Split(string(data), "\n") {
		line := strings.TrimSpace(raw)
		if line == "" {
			continue
		}
		var obj map[string]any
		if err := json.Unmarshal([]byte(line), &obj); err != nil {
			continue
		}
		msg, ok := obj["message"].(map[string]any)
		if !ok {
			continue
		}
		if role, _ := msg["role"].(string); role != "assistant" {
			continue
		}
		blocks := textBlocks(msg["content"])
		if len(blocks) > 0 {
			turns = append(turns, strings.Join(blocks, "\n"))
		}
	}
	if len(turns) == 0 {
		return ""
	}
	if lastTurns < len(turns) {
		turns = turns[len(turns)-lastTurns:]
	}
	return strings.Join(turns, "\n")
}

// textBlocks pulls text from a message `content` (a str, or a list of typed blocks).
// Port of claim_extract._text_blocks. Mirrors scripts/trajectory_audit.py so the two
// transcript readers can't drift.
func textBlocks(content any) []string {
	switch c := content.(type) {
	case string:
		return []string{c}
	case []any:
		var texts []string
		for _, b := range c {
			bm, ok := b.(map[string]any)
			if !ok {
				continue
			}
			if t, _ := bm["type"].(string); t != "text" {
				continue
			}
			if t, ok := bm["text"].(string); ok && t != "" {
				texts = append(texts, t)
			}
		}
		return texts
	}
	return nil
}

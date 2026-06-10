package hook

// verify.go — the native port of the verify() truth syscall's grep rung, scoped to
// what fires on a GENERIC StampConvention repo (docs/125 §8.2.1). The empirical probe
// (parity/probe_verify_rungs.py) found that on this repo's REAL history the only grep
// rung that resolves a ship is `direct` (8/8), graded `source=grep-subject`. So this
// file ports Pass 1a (the direct-ship scan) faithfully. But the release-prefix scan
// (Pass 1b) is anchored on a HARDCODED `vX.Y.Z:` subject (`summary_subject` resolves
// to `(?:v\d+\.\d+\.\d+:)` even under the generic convention — it is NOT gated on a
// declared summary_bundle_prefixes), so it CAN fire on a release commit that bundles a
// `<PHASE>` mention. This file does not port that scan; instead it DETECTS a release-
// anchored subject in the window and ABSTAINS (delegates to Python) — never reporting a
// clean miss when a rung it does not own might resolve a ship. The remaining non-direct
// rungs (body, hyg-slug, sub-phase-parent, file-path) require a declared convention /
// plan-doc and are inert on the no-plan generic stop path, so isGeneric() abstains
// before them.
//
// The decider is PURE: verifyDirect(plan, phase, onelineLines, conv) -> verifyVerdict.
// The git-log read is the boundary I/O, done by the stop path (stop.go) and injected
// here, mirroring the kernel's "I/O at the boundary, data to the pure core" rule and
// the pretool corpus's injected leases/runtime_files.
//
// Byte-faithfulness argument (vs phase_shipped._check_phase_with_cache, generic conv):
//   - direct_pat is built per-(plan,phase) from re.escape'd inputs. Go's
//     regexp.QuoteMeta and Python's re.escape escape DIFFERENT character sets, but
//     both leave the matched LANGUAGE identical (escaping a non-special char like
//     `/` or `-` is a semantic no-op). So the compiled patterns match the same
//     strings — language-equality, which is what the verdict depends on, not
//     byte-equal pattern text.
//   - The generic direct core is `(?:<prefixed>|<glued>)` where
//       prefixed = (?:\w[\w.\-]*/)? <SERIES>:?\s+(?:<PHASE-alt>)
//       glued    = (?:\w[\w.\-]*/)? (?:<SERIES>)?(?:<PHASE-alt>):
//     anchored `^([a-f0-9]+)\s+...` with a trailing `(?![A-Za-z0-9.\-])` lookahead
//     (RE2-native — NOT the lookbehind blocker, which only the release/body scans use).
//   - Generic convention disables: progress-marker demotion (empty set → _is_progress_only
//     always False), bookkeeping has only the two universal guards (snapshot, run-archive).
//   - Pass 1a returns the FIRST oneline match (newest-first log order) that is not a
//     bookkeeping subject and not progress-only.

import (
	"regexp"
	"strings"
)

// verifyVerdict is the native verify outcome for one (plan, phase). `supported` is
// false when the direct rung did not match AND a not-yet-ported rung MIGHT have — in
// that case the stop path must DELEGATE to Python rather than report NOT_SHIPPED off
// an incomplete port (a subtly-wrong verify blocks a legitimate stop). When the direct
// rung matches, supported=true + shipped=true. When the direct rung misses and no
// unsupported rung could fire (the generic-convention common case), supported=true +
// shipped=false.
type verifyVerdict struct {
	plan      string
	phase     string
	shipped   bool
	sha       string
	summary   string
	via       string // "direct" on a hit, "" otherwise
	source    string // "grep-subject" on a direct hit, "none" on a clean miss
	supported bool   // false → the caller must DELEGATE to Python (an unported rung might fire)
}

// genericConvention is the resolved generic StampConvention's fragments the native
// verify needs. Built from the workspace's dos.toml [stamp] table (genericConventionFromToml).
// Only the fields the direct rung + the abstain gate consult are carried; the rest
// (code_dirs, infra_*) belong to rungs this file abstains on.
type genericConvention struct {
	subjectDirs           []string // empty → the dir prefix is the optional single-segment form
	summaryBundlePrefixes []string // empty (generic) → only the vX.Y.Z: release anchor
	bookkeepingPrefixes   []string // empty (generic) → only the two universal guards
	progressMarkers       []string // empty (generic) → _is_progress_only never demotes
	subPhaseParentFallback bool    // false (generic) → that rung never runs
}

// isGeneric reports whether this is the pure generic convention (every list empty,
// no sub-phase fallback) — the shape this repo and any default foreign repo carry.
// The native verify is byte-complete ONLY for the generic convention; a declared
// [stamp] with subject_dirs / summary_bundle_prefixes / progress_markers makes the
// release/body/progress rungs live, which this file does not port → abstain.
func (c genericConvention) isGeneric() bool {
	return len(c.subjectDirs) == 0 &&
		len(c.summaryBundlePrefixes) == 0 &&
		len(c.bookkeepingPrefixes) == 0 &&
		len(c.progressMarkers) == 0 &&
		!c.subPhaseParentFallback
}

// Go's regexp (RE2) does NOT support lookahead `(?!...)`. The Python direct_pat ends
// with `(?![A-Za-z0-9.\-])` to forbid an alnum/dot/hyphen immediately after the match.
// RE2 rewrite (the standard transform): instead of a zero-width negative lookahead at
// the match end, we (a) compile WITHOUT the trailing guard, then (b) check the byte
// IMMEDIATELY AFTER the regexp match end against the forbidden class in Go code, and
// reject the match if it is alnum/dot/hyphen. This reproduces the lookahead's effect
// exactly: the match is accepted iff the next char is end-of-string or a non-[A-Za-z0-9.-]
// char. Anchoring `^([a-f0-9]+)\s+` makes each line a single deterministic match start,
// so a rejected match means the line does not ship the phase (no backtracking-to-a-
// shorter-alternative concern: the phase alternation tokens here are fixed strings).

var _forbiddenAfterToken = regexp.MustCompile(`[A-Za-z0-9.\-]`)

// phaseVariants — port of phase_shipped._phase_variants for the GENERIC convention
// (no series-qualified synonym expansion is needed here because: a generic `Phase N`
// query path is the _is_generic_phase_token branch, which this file abstains on via
// isGeneric()'s caller scoping — a real generic-repo phase id like `liveness`/`GHF2`/`F4`
// is NOT a `Phase N` token). The apostrophe↔prime spelling pair is ported (it is
// convention-blind). Returns regexp-QUOTED variants, sorted, matching Python's
// `sorted(re.escape(v) for v in variants)`.
func phaseVariants(phase string) []string {
	set := map[string]struct{}{phase: {}}
	if strings.Contains(phase, "'") {
		set[strings.ReplaceAll(phase, "'", "prime")] = struct{}{}
	}
	if strings.Contains(phase, "prime") {
		set[strings.ReplaceAll(phase, "prime", "'")] = struct{}{}
	}
	// NOTE: the series-qualified `Phase N`↔`<SERIES>N` synonym expansion
	// (_phase_variants' `if series:` branch) only triggers for a generic `Phase N`
	// token or a `<SERIES><num>` token whose stem == series. A real generic-repo
	// phase id (`liveness`, `GHF2`, `F4`, `marker_sensor`) is neither (the stem of
	// `GHF2` is `GHF`, never equal to a `docs/125_x` series), so the synonym branch
	// is inert here. The corpus pins this: if a phase ever needed the synonym, the
	// differential gate would catch the divergence and we'd abstain.
	out := make([]string, 0, len(set))
	for v := range set {
		out = append(out, regexp.QuoteMeta(v))
	}
	sortStrings(out)
	return out
}

// directShipCore — port of StampConvention.direct_ship_core for the GENERIC branch
// (subject_dirs empty): `(?:<prefixed>|<glued>)`. seriesRE and phaseAlt are already
// QuoteMeta'd / `|`-joined fragments (built by the caller from phaseVariants).
func (c genericConvention) directShipCore(seriesRE, phaseAlt string) string {
	prefix := c.directPrefixRE()
	prefixed := prefix + seriesRE + `:?\s+(?:` + phaseAlt + `)`
	if len(c.subjectDirs) > 0 {
		return prefixed
	}
	glued := prefix + `(?:` + seriesRE + `)?(?:` + phaseAlt + `):`
	return `(?:` + prefixed + `|` + glued + `)`
}

// directPrefixRE — port of StampConvention.direct_prefix_re. Generic (no subject_dirs)
// → the OPTIONAL single-component path prefix `(?:\w[\w.\-]*/)?` (NOT a greedy `.*`,
// NOT multi-segment — the adversarial-review tightening). With subject_dirs declared
// → the required `(?:docs|go|…)/` alternation (this file abstains before reaching the
// declared-dir path via isGeneric(), so the generic branch is what runs).
func (c genericConvention) directPrefixRE() string {
	if len(c.subjectDirs) > 0 {
		quoted := make([]string, len(c.subjectDirs))
		for i, d := range c.subjectDirs {
			quoted[i] = regexp.QuoteMeta(d)
		}
		return `(?:` + strings.Join(quoted, "|") + `)/`
	}
	return `(?:\w[\w.\-]*/)?`
}

// verifyDirect runs the native direct-ship grep rung over the injected oneline log
// lines. PURE (the git read is the caller's boundary I/O). Returns the verifyVerdict;
// when the convention is not pure-generic it returns supported=false (abstain), and
// when the direct rung misses it returns supported=true, shipped=false (the generic
// path has no other rung that fires on a real ship here — proven by the probe and
// pinned by the corpus).
func verifyDirect(plan, phase string, onelineLines []string, conv genericConvention) verifyVerdict {
	v := verifyVerdict{plan: plan, phase: phase}

	// Only the pure-generic convention is byte-complete natively. A declared [stamp]
	// (subject_dirs / summary_bundle_prefixes / progress_markers / sub-phase fallback)
	// activates rungs this file does not port → delegate.
	if !conv.isGeneric() {
		v.supported = false
		return v
	}
	// A generic `Phase N` token would route through the _is_generic_phase_token
	// release/body series-qualification — a path this file does not port. A real
	// generic-repo phase id never takes that shape; if one does, abstain.
	if isGenericPhaseToken(phase) {
		v.supported = false
		return v
	}

	seriesRE := regexp.QuoteMeta(plan)
	phaseAlt := strings.Join(phaseVariants(phase), "|")
	core := conv.directShipCore(seriesRE, phaseAlt)
	// Compile WITHOUT the trailing lookahead; enforce the boundary in code (the RE2
	// rewrite of `(?![A-Za-z0-9.\-])`). `(?i)` reproduces re.IGNORECASE.
	pat, err := regexp.Compile(`(?i)^([a-f0-9]+)\s+` + core)
	if err != nil {
		// A pattern that fails to compile in RE2 (it should not for these inputs) →
		// abstain rather than silently miss.
		v.supported = false
		return v
	}

	// Pass 1a: the first direct-ship line wins (oneline is newest-first). Skip a
	// bookkeeping subject and a progress-only tail (the latter never fires generic).
	for _, line := range onelineLines {
		loc := pat.FindStringSubmatchIndex(line)
		if loc == nil {
			continue
		}
		// Enforce the right-edge boundary: the byte at the match end must not be
		// [A-Za-z0-9.-]. loc[1] is the end offset of the whole match.
		if !boundaryOK(line, loc[1]) {
			continue
		}
		subject := onelineSubject(line)
		if conv.isBookkeepingSubject(subject) {
			continue
		}
		if conv.isProgressOnly(line, loc[1]) { // always false under generic
			continue
		}
		sha := line[loc[2]:loc[3]] // group(1)
		v.shipped = true
		v.sha = sha
		v.summary = line
		v.via = "direct"
		v.source = "grep-subject"
		v.supported = true
		return v
	}

	// No direct ship. Before reporting a clean miss, check the ONE non-direct rung
	// that fires even under the pure-generic convention: the release-prefix scan
	// (Pass 1b). It is anchored on a hardcoded `vX.Y.Z:` subject regardless of declared
	// [stamp], so a release commit that BUNDLES this phase's id into its summary can
	// ship it. If the native release scan matches THIS phase on a release-anchored,
	// non-bookkeeping subject, Python's Pass 1b would resolve the same ship via a rung
	// this file does not own — so the native path cannot honestly report a clean miss
	// and ABSTAINS, delegating to Python. (A release subject that does NOT mention this
	// phase does not trigger the abstain — that is the common real-history case where
	// the window holds releases for OTHER phases.)
	if releaseScanHits(plan, phase, onelineLines, conv) {
		v.supported = false
		return v
	}

	// No direct ship and no release subject resolves this phase → under the pure-
	// generic convention no other rung resolves a real ship (probe-proven, corpus-
	// pinned), so report a clean miss.
	v.shipped = false
	v.source = "none"
	v.supported = true
	return v
}

// releaseScanHits ports phase_shipped's Pass-1b release-prefix scan for the GENERIC,
// non-`Phase N` branch (the only shape the native stop path reaches — a generic
// `Phase N` token already abstained via isGenericPhaseToken). It reports whether any
// release-anchored (`vX.Y.Z:`), non-bookkeeping oneline subject mentions this phase
// with the same boundary guards Python uses. A hit means the native path must ABSTAIN
// (Python's Pass 1b would fire), so this returns a boolean — NOT a ship verdict (the
// native path does not OWN the release rung; it only recognises when to defer).
//
// Python pattern (non-generic-token branch):
//
//	^([a-f0-9]+)\s+(?:v\d+\.\d+\.\d+:).*?(?<!BND)(?:<release_alt>)(?!BND)
//
// where BND = [A-Za-z0-9.\-] and release_alt = _release_body_alternation(series,phase).
// RE2 has no lookbehind/lookahead, so the alternation is compiled bare and BOTH edges
// are checked in code (left via boundaryOK on the byte BEFORE the match start, right via
// the existing boundaryOK on the match end), reproducing _BOUNDARY_PRE_NEG/_BOUNDARY_NEG.
func releaseScanHits(plan, phase string, onelineLines []string, conv genericConvention) bool {
	alt := releaseBodyAlternation(plan, phase)
	if alt == "" {
		return false
	}
	// `(?i)^([a-f0-9]+)\s+(?:v\d+\.\d+\.\d+:).*?(<alt>)` — `.*?` is lazy in RE2 too;
	// FindStringSubmatchIndex returns the leftmost match, and we boundary-check its
	// edges. The version anchor is the hardcoded generic summary_subject.
	pat, err := regexp.Compile(`(?i)^[a-f0-9]+\s+v\d+\.\d+\.\d+:.*?(` + alt + `)`)
	if err != nil {
		// A release alternation that fails to compile → be safe and abstain (treat as a
		// potential hit) rather than risk a wrong clean miss.
		return true
	}
	for _, line := range onelineLines {
		loc := pat.FindStringSubmatchIndex(line)
		if loc == nil {
			continue
		}
		// loc[2]:loc[3] is group(1) — the phase-token match. Enforce both boundary
		// guards: the byte BEFORE the match start (_BOUNDARY_PRE_NEG) and the byte AFTER
		// the match end (_BOUNDARY_NEG) must each be outside [A-Za-z0-9.-]. At SOL/EOL the
		// guard is satisfied (nothing there to forbid).
		start, end := loc[2], loc[3]
		leftOK := start == 0 || !_forbiddenAfterToken.MatchString(line[start-1:start])
		if !leftOK || !boundaryOK(line, end) {
			continue
		}
		// FQ-77: a bookkeeping subject (snapshot / archive <run-id>) NAMES a phase but
		// never ships it — Python's Pass 1b skips it, so the native abstain must not fire
		// on it either (else a snapshot subject in the window would force a needless
		// delegate). Under generic convention only the two universal guards apply.
		if conv.isBookkeepingSubject(onelineSubject(line)) {
			continue
		}
		return true
	}
	return false
}

// releaseBodyAlternation ports phase_shipped._release_body_alternation for the GENERIC
// convention. For each phase variant: keep it bare if it contains the series (plan)
// token case-insensitively (self-qualifying, e.g. `EC17` for series `EC`); a generic
// `Phase N` synonym is rebuilt as `<SERIES>\s*:?\s+Phase\s*N`; anything else is kept.
// Returns the `|`-joined alternation (already QuoteMeta'd fragments), or "" if empty.
func releaseBodyAlternation(plan, phase string) string {
	seriesRE := regexp.QuoteMeta(plan)
	var safe []string
	for _, variant := range phaseVariants(phase) { // variants are already QuoteMeta'd
		unq := unquoteMeta(variant)
		if plan != "" && strings.Contains(strings.ToLower(unq), strings.ToLower(plan)) {
			safe = append(safe, variant)
			continue
		}
		if gm := _genericPhaseNumRE.FindStringSubmatch(unq); gm != nil {
			numRE := regexp.QuoteMeta(gm[1])
			safe = append(safe, seriesRE+`\s*:?\s+Phase\s*`+numRE)
			continue
		}
		safe = append(safe, variant)
	}
	return strings.Join(safe, "|")
}

// _genericPhaseNumRE captures N from a bare `Phase N` token (the _GENERIC_PHASE_RE
// capture group), used by releaseBodyAlternation to rebuild a generic synonym as a
// series-adjacent form.
var _genericPhaseNumRE = regexp.MustCompile(`(?i)^phase\s*(\d+(?:\.\d+)?)$`)

// unquoteMeta reverses regexp.QuoteMeta enough to test a variant's text for the series
// substring and the generic-`Phase N` shape — QuoteMeta only inserts a backslash before
// an ASCII metacharacter, and the series/`Phase N` tokens are alnum+space, so dropping
// the escaping backslashes recovers the literal. Mirrors Python's `re.sub(r"\\(.)", r"\1", v)`.
func unquoteMeta(s string) string {
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		if s[i] == '\\' && i+1 < len(s) {
			i++
			b.WriteByte(s[i])
			continue
		}
		b.WriteByte(s[i])
	}
	return b.String()
}

// boundaryOK reports whether the char at byte offset `end` in `line` satisfies the
// negative-lookahead guard `(?![A-Za-z0-9.\-])`: true iff end is at/after the line's
// length (end-of-string) OR the byte there is not in [A-Za-z0-9.-].
func boundaryOK(line string, end int) bool {
	if end >= len(line) {
		return true
	}
	return !_forbiddenAfterToken.MatchString(line[end : end+1])
}

// onelineSubject — port of phase_shipped._oneline_subject: the bare summary from a
// `<sha> <summary>` oneline (split off the leading sha token). A line with no space
// yields "".
func onelineSubject(line string) string {
	// Python's line.split(None, 1): split on the FIRST run of whitespace.
	i := strings.IndexAny(line, " \t")
	if i < 0 {
		return ""
	}
	rest := strings.TrimLeft(line[i:], " \t")
	return rest
}

// isGenericPhaseToken — port of phase_shipped._is_generic_phase_token: a bare
// `Phase N` token with no series prefix. `_GENERIC_PHASE_RE = (?i)^phase\s*(\d+(?:\.\d+)?)$`.
var _genericPhaseRE = regexp.MustCompile(`(?i)^phase\s*\d+(?:\.\d+)?$`)

func isGenericPhaseToken(phase string) bool {
	return _genericPhaseRE.MatchString(strings.TrimSpace(phase))
}

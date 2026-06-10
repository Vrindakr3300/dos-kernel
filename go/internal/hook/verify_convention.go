package hook

// verify_convention.go — the genericConvention's bookkeeping + progress-marker
// predicates (port of dos.stamp.StampConvention for the generic case) and the
// minimal dos.toml [stamp] reader. Kept beside verify.go so the direct rung and its
// convention helpers read as one unit.

import (
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// The two UNIVERSAL bookkeeping guards — host-agnostic, present in every convention's
// bookkeeping regex regardless of declared prefixes (port of stamp._SNAPSHOT_*/
// _RUN_ARCHIVE_* fragments). A subject matching either NAMES phase ids as narrative
// (a bulk snapshot, or a run-archive rollup that quotes the run ids it archives) and
// must never count as a ship.
//
//	snapshot:      `[^:]*\bsnapshot:`
//	run-archive:   `(?:[^:]*:\s*)?(?:archive|rollup)\s+\d{8}(?:t\d+z?)?\b`
//
// Compiled start-anchored + case-insensitive (port of bookkeeping_subject_re:
// `^(?:...)` with re.IGNORECASE). Both fragments are RE2-native.
var _bookkeepingUniversalRE = regexp.MustCompile(
	`(?i)^(?:` +
		`[^:]*\bsnapshot:` +
		`|(?:[^:]*:\s*)?(?:archive|rollup)\s+\d{8}(?:t\d+z?)?\b` +
		`)`,
)

// isBookkeepingSubject — port of _Matchers.is_bookkeeping_subject → StampConvention.
// bookkeeping_subject_re().match(subject.strip()). For the GENERIC convention the
// declared bookkeeping_prefixes are empty, so only the two universal guards apply.
// `subject` is the bare commit summary (sha already stripped by onelineSubject).
func (c genericConvention) isBookkeepingSubject(subject string) bool {
	s := strings.TrimSpace(subject)
	if c.matchesDeclaredBookkeeping(s) {
		return true
	}
	return _bookkeepingUniversalRE.MatchString(s)
}

// matchesDeclaredBookkeeping handles any declared bookkeeping_prefixes (empty under
// generic → always false). Kept so a future declared-prefix convention reuses the
// same predicate; the prefixes are matched start-anchored, case-insensitively, as
// re.escape'd literals (the Python builds `re.escape(p)` alternatives).
func (c genericConvention) matchesDeclaredBookkeeping(s string) bool {
	if len(c.bookkeepingPrefixes) == 0 {
		return false
	}
	lower := strings.ToLower(s)
	for _, p := range c.bookkeepingPrefixes {
		if strings.HasPrefix(lower, strings.ToLower(p)) {
			return true
		}
	}
	return false
}

// isProgressOnly — port of phase_shipped._is_progress_only. True if what follows the
// matched phase id reads as a progress marker (`<PHASE> week-1`/`<PHASE> audit`). For
// the GENERIC convention the progress-marker set is EMPTY, so this is ALWAYS false —
// a generic-repo ship is never demoted (the L1 fix). Ported in full for fidelity:
// a separator (`:`/`—`/`-`/EOL) immediately after the id reads as a ship; only a bare
// `<PHASE> <progress-word>` shape would demote.
func (c genericConvention) isProgressOnly(line string, matchEnd int) bool {
	if matchEnd >= len(line) {
		return false // EOL — ship
	}
	tail := line[matchEnd:]
	// `not tail[0].isspace()` → not a space → ship (`:`/`—`/`-`/non-space).
	if !isPySpace(rune(tail[0])) {
		return false
	}
	markers := c.progressMarkerSet()
	if len(markers) == 0 {
		return false // generic: no progress vocabulary → never demote
	}
	trimmed := strings.TrimSpace(tail)
	if trimmed == "" {
		return false
	}
	// next_token = tail.lstrip().split(None, 1)[0]
	nextToken := strings.FieldsFunc(strings.TrimLeft(tail, " \t\n\r\f\v"), func(r rune) bool {
		return isPySpace(r)
	})
	if len(nextToken) == 0 {
		return false
	}
	_, ok := markers[strings.ToLower(nextToken[0])]
	return ok
}

// progressMarkerSet returns the lowercased progress markers as a set (empty generic).
func (c genericConvention) progressMarkerSet() map[string]struct{} {
	if len(c.progressMarkers) == 0 {
		return nil
	}
	m := make(map[string]struct{}, len(c.progressMarkers))
	for _, w := range c.progressMarkers {
		m[strings.ToLower(w)] = struct{}{}
	}
	return m
}

// isPySpace mirrors Python str.isspace() for the ASCII whitespace that appears in a
// commit oneline: space, tab, newline, carriage return, form feed, vertical tab.
func isPySpace(r rune) bool {
	switch r {
	case ' ', '\t', '\n', '\r', '\f', '\v':
		return true
	}
	return false
}

// sortStrings sorts in ascending byte order (Python's sorted() on the escaped
// variant strings — ASCII, so byte order == code-point order).
func sortStrings(s []string) { sort.Strings(s) }

// ---------------------------------------------------------------------------
// The minimal dos.toml [stamp] reader. The native verify is byte-complete only for
// the pure-generic convention; a DECLARED [stamp] table (subject_dirs / summary_
// bundle_prefixes / progress_markers / sub_phase_parent_fallback) activates rungs
// this file abstains on, so the reader's job is mainly to DETECT a non-generic
// declaration and surface it (the caller then abstains). We read the same dos.toml
// the lane-journal reader scans, dependency-free.
// ---------------------------------------------------------------------------

// readStampConvention scans the workspace's dos.toml [stamp] table for the fields the
// native verify cares about. Absent file / absent [stamp] table / empty table → the
// pure-generic convention (every list empty), which is exactly what this repo and any
// default foreign repo carry. A present-but-declared field is captured so isGeneric()
// returns false and the caller delegates. NOT a full TOML parser — it recognizes the
// `[stamp]` header and the list/bool keys it needs; anything it cannot parse leaves
// the field at its generic default (the safe direction: under-reading a declaration
// makes isGeneric() MORE likely to be true, which only widens the abstain — never a
// wrong native verdict, because a declared non-generic field that we miss would make
// the native scan diverge from Python and the corpus would catch it).
//
// IMPORTANT subtlety: the JOB convention is the DEFAULT base when a repo declares a
// [stamp] table with `style="grep"` only — BUT only if the loader uses JOB as the
// base. In practice a DOS workspace's dos.toml carries `[stamp] style="grep"` with no
// other key, and config.load_workspace_config layers it over the GENERIC default
// (the workspace is a kernel repo). So the resolved convention is generic. We verify
// this matches the active Python convention via the corpus generator (which reads the
// live config), so any base-resolution surprise is caught there, not assumed here.
func readStampConvention(workspace string) genericConvention {
	conv := genericConvention{} // pure-generic default
	data, err := os.ReadFile(filepath.Join(workspace, "dos.toml"))
	if err != nil {
		return conv
	}
	lines := strings.Split(strings.ReplaceAll(string(data), "\r\n", "\n"), "\n")
	inStamp := false
	for _, raw := range lines {
		line := strings.TrimSpace(raw)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if strings.HasPrefix(line, "[") {
			inStamp = line == "[stamp]"
			continue
		}
		if !inStamp {
			continue
		}
		key, val, ok := splitTomlKey(line)
		if !ok {
			continue
		}
		switch key {
		case "subject_dirs":
			conv.subjectDirs = parseTomlStringList(val)
		case "summary_bundle_prefixes":
			conv.summaryBundlePrefixes = parseTomlStringList(val)
		case "bookkeeping_prefixes":
			conv.bookkeepingPrefixes = parseTomlStringList(val)
		case "progress_markers":
			conv.progressMarkers = parseTomlStringList(val)
		case "sub_phase_parent_fallback":
			conv.subPhaseParentFallback = strings.Contains(strings.ToLower(val), "true")
		}
	}
	return conv
}

// splitTomlKey splits a `key = value` line, stripping an inline comment outside the
// value's quotes. Returns ok=false for a line with no `=`.
func splitTomlKey(line string) (key, val string, ok bool) {
	eq := strings.IndexByte(line, '=')
	if eq < 0 {
		return "", "", false
	}
	key = strings.TrimSpace(line[:eq])
	val = strings.TrimSpace(line[eq+1:])
	return key, val, true
}

// parseTomlStringList parses a `["a", "b"]` inline-array value into its string
// elements. A non-array / empty `[]` yields an empty (non-nil-significant) slice. Only
// single-line inline arrays are recognized (the only shape a [stamp] list takes); a
// multiline array would leave the field empty → wider abstain (safe). An element's
// surrounding quotes are stripped.
func parseTomlStringList(val string) []string {
	val = strings.TrimSpace(val)
	// Drop a trailing inline comment after the closing bracket.
	if i := strings.LastIndexByte(val, ']'); i >= 0 {
		val = val[:i+1]
	}
	if !strings.HasPrefix(val, "[") || !strings.HasSuffix(val, "]") {
		return nil
	}
	inner := strings.TrimSpace(val[1 : len(val)-1])
	if inner == "" {
		return nil
	}
	var out []string
	for _, part := range strings.Split(inner, ",") {
		p := strings.TrimSpace(part)
		p = strings.Trim(p, `"'`)
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}

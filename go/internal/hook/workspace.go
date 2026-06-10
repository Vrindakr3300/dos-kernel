package hook

import (
	"os"
	"path/filepath"
	"strings"
)

// ResolveWorkspace resolves the served workspace root the way the kernel's
// `SubstrateConfig` seam does for the hook path: an explicit value (the
// --workspace flag, or the event's cwd) › the DISPATCH_WORKSPACE env › the process
// cwd. Returns an absolute path. The kernel NEVER anchors on __file__; neither does
// the Go binary — it resolves against the served workspace, exactly like the rest
// of the seam (the "package never assumes it lives in the repo it serves" litmus).
func ResolveWorkspace(explicit string) string {
	if explicit != "" {
		if abs, err := filepath.Abs(explicit); err == nil {
			return abs
		}
		return explicit
	}
	if env := os.Getenv("DISPATCH_WORKSPACE"); env != "" {
		if abs, err := filepath.Abs(env); err == nil {
			return abs
		}
		return env
	}
	if cwd, err := os.Getwd(); err == nil {
		return cwd
	}
	return "."
}

// JournalPath resolves the lane-journal WAL path the SAME way
// `dos.lane_lease._journal_path` does: the DISPATCH_LANE_JOURNAL_PATH /
// JOB_LANE_JOURNAL_PATH env override › the workspace's configured lane journal.
//
// The configured path defaults to the generic `.dos/` layout
// (`PathLayout.for_dos_dir` -> `<workspace>/.dos/lane-journal.jsonl`), which is the
// active layout for a default DOS workspace (`config.config` uses for_dos_dir). A
// `dos.toml [paths] lane_journal = "..."` override, if present, is honored via a
// minimal scan (no full TOML parser on the hot path) — a relative value resolves
// against the workspace root, an absolute value is taken as-is. This keeps the Go
// reader pointed at the SAME WAL the Python writer appends to, so the live leases
// agree.
func JournalPath(workspace string) string {
	if env := os.Getenv("DISPATCH_LANE_JOURNAL_PATH"); env != "" {
		return env
	}
	if env := os.Getenv("JOB_LANE_JOURNAL_PATH"); env != "" {
		return env
	}
	if override := laneJournalOverrideFromToml(workspace); override != "" {
		if filepath.IsAbs(override) {
			return override
		}
		return filepath.Join(workspace, filepath.FromSlash(override))
	}
	return filepath.Join(workspace, ".dos", "lane-journal.jsonl")
}

// laneJournalOverrideFromToml does a minimal, dependency-free scan of the
// workspace's dos.toml for a `[paths] lane_journal = "..."` override. It is NOT a
// TOML parser: it finds the `[paths]` table header and the first `lane_journal =`
// key within it, reading a double- or single-quoted string value. Anything it
// cannot parse confidently yields "" (fall back to the `.dos/` default — the safe
// direction: a missed override degrades to the common layout, and the parity
// corpus is built on the default layout). The vast majority of workspaces (incl.
// this repo) never override lane_journal, so this almost always returns "".
func laneJournalOverrideFromToml(workspace string) string {
	data, err := os.ReadFile(filepath.Join(workspace, "dos.toml"))
	if err != nil {
		return ""
	}
	lines := strings.Split(strings.ReplaceAll(string(data), "\r\n", "\n"), "\n")
	inPaths := false
	for _, raw := range lines {
		line := strings.TrimSpace(raw)
		if strings.HasPrefix(line, "#") || line == "" {
			continue
		}
		if strings.HasPrefix(line, "[") {
			inPaths = line == "[paths]"
			continue
		}
		if !inPaths {
			continue
		}
		if strings.HasPrefix(line, "lane_journal") {
			eq := strings.IndexByte(line, '=')
			if eq < 0 {
				return ""
			}
			val := strings.TrimSpace(line[eq+1:])
			val = stripInlineComment(val)
			return unquoteToml(val)
		}
	}
	return ""
}

// stripInlineComment removes a trailing ` # ...` comment outside a quoted string.
// Minimal: it only trims a comment that begins after the closing quote of a quoted
// value (the only shape lane_journal would take), so a `#` inside the quoted path
// is preserved.
func stripInlineComment(val string) string {
	if len(val) == 0 {
		return val
	}
	q := val[0]
	if q == '"' || q == '\'' {
		if end := strings.IndexByte(val[1:], q); end >= 0 {
			return val[:end+2]
		}
	}
	return val
}

func unquoteToml(val string) string {
	val = strings.TrimSpace(val)
	if len(val) >= 2 {
		if (val[0] == '"' && val[len(val)-1] == '"') || (val[0] == '\'' && val[len(val)-1] == '\'') {
			return val[1 : len(val)-1]
		}
	}
	return ""
}

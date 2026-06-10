package hook

// stop.go — the native port of cli.cmd_hook_stop (docs/134 §2/§2.2, docs/125 GHF
// native stop). A `Stop`/`SubagentStop` hook: refuse to let an agent stop on a false
// done. Reads the host's Stop event on stdin, extracts the (plan, phase) the agent
// CLAIMED it shipped (claim_extract), and verifies each against git (verify.go's
// direct grep rung). If any CONFIDENT claim is NOT_SHIPPED, emits the EXACT
// Claude-Code Stop dialect
//
//	{"decision": "block", "reason": "<verdict fed back as the next task>"}
//
// at exit 0 (CC's "keep working" signal), so CC declines to stop. Otherwise emits
// nothing and exits 0 (let the agent stop). Every failure mode degrades to
// "let it stop": a missing transcript, unparseable stdin, an extractor abstention,
// an already-active stop. The hook refuses a FALSE done; it never blocks a TRUE one
// or crashes the host turn (the fail-safe direction).
//
// The git-log read is the BOUNDARY I/O — done once here and passed to verifyDirect's
// pure core (the "I/O at the boundary, data to the pure core" rule). The native path
// OWNS the default-dialect common case and DELEGATES (exit 3 → the hooks.json `||`
// Python) on the uncommon flags it does not serve (--json, --strict, --force,
// --plan/--phase frontmatter claims) and whenever verify ABSTAINS (an unported rung
// might fire) — so a native miss never blocks a legitimate stop.

import (
	"encoding/json"
	"fmt"
	"io"
	"os/exec"
	"strings"
)

// StopResult is the native Stop outcome the dispatcher acts on:
//   - Handled=false  => DELEGATE to Python (exit 3): an uncommon flag or an abstaining
//     verify means the native path cannot own this decision; the `||` Python re-decides.
//   - Handled=true, Stdout=="" => let the agent stop (emit nothing, exit 0).
//   - Handled=true, Stdout=`{"decision":"block",…}` => block (emit it, exit 0).
type StopResult struct {
	Handled bool
	Stdout  string
	Obs     Observation // the observability projection (docs/276): block/let/delegate + claims seen + the blocked (plan,phase)
}

// StopOptions carries the flags the native path inspects. The hooks.json wiring is
// `dos hook stop --workspace .` (no extra flags), so the native path serves the
// zero-flag default and delegates when any advanced flag is set.
type StopOptions struct {
	WorkspaceFlag string
	Plan          string // --plan (frontmatter claim) → delegate if set
	Phase         string // --phase → delegate if set
	LastTurns     int    // --last-turns (default 1)
	Strict        bool   // --strict → delegate if set
	Force         bool   // --force → delegate if set
	JSON          bool   // --json → delegate if set
}

// gitLogReader reads the oneline log window for the verify rung. Injectable so the
// differential corpus can run verifyDirect against an injected log without shelling git.
type gitLogReader func(workspace string) []string

// DecideStop runs the native Stop decider. `runGitLog` defaults to the real git shell
// when nil. PURE except for the transcript read and the git-log read (both at the
// boundary). debug, when non-nil, receives a trace.
func DecideStop(stdinBytes []byte, opts StopOptions, runGitLog gitLogReader, debug io.Writer) StopResult {
	dbg := func(format string, a ...any) {
		if debug != nil {
			fmt.Fprintf(debug, "[dos-hook stop] "+format+"\n", a...)
		}
	}

	// The native path serves only the zero-flag default dialect. Any advanced flag
	// → DELEGATE (the Python verb owns the --json object, the --strict heuristic
	// blocking, the --force guard override, and the frontmatter claim path).
	if opts.JSON || opts.Strict || opts.Force || opts.Plan != "" || opts.Phase != "" {
		dbg("advanced flag set — delegating to Python")
		recordStop("delegate", 0, nil)
		return StopResult{Handled: false, Obs: Observation{Outcome: "delegate"}}
	}

	// 1. Parse the Stop event from stdin. Any failure → an empty event (we never block
	//    on our own inability to read). Unlike pretool/posttool, an empty/garbled event
	//    here does NOT delegate — the Python path would also let-it-stop on it, so the
	//    native let-it-stop (exit 0, nothing) is byte-identical and faster.
	var event map[string]any
	if len(strings.TrimSpace(string(stdinBytes))) > 0 {
		if err := json.Unmarshal(stdinBytes, &event); err != nil {
			event = nil
		}
	}

	// 2. Anti-loop guard: if CC is already in a forced continuation from a prior Stop
	//    block, bow out (let it stop) — one push-back per work stretch. (--force, which
	//    overrides this, already delegated above.)
	if event != nil {
		if active, _ := event["stop_hook_active"].(bool); active {
			dbg("stop_hook_active — letting the agent stop")
			recordStop("all-verified", 0, nil) // an already-continued stop is a let, not a verdict
			return StopResult{Handled: true, Obs: Observation{Outcome: "let-active"}} // emit nothing
		}
	}

	// 3. Resolve the workspace: --workspace › the event's cwd › cwd.
	wsArg := opts.WorkspaceFlag
	if wsArg == "" && event != nil {
		if c, ok := event["cwd"].(string); ok {
			wsArg = c
		}
	}
	workspace := ResolveWorkspace(wsArg)

	// 4. Gather claims. The frontmatter rung already delegated (--plan/--phase). So
	//    only the transcript rungs run here. --last-turns defaults to 1.
	lastTurns := opts.LastTurns
	if lastTurns < 1 {
		lastTurns = 1
	}
	transcriptPath := ""
	if event != nil {
		if t, ok := event["transcript_path"].(string); ok {
			transcriptPath = t
		}
	}
	var claims []Claim
	if transcriptPath != "" {
		text := assistantTextFromTranscript(transcriptPath, lastTurns)
		// allow_heuristic = args.strict, and --strict already delegated → false here.
		claims = extractClaims(text, false)
	}

	if len(claims) == 0 {
		// Nothing the agent confidently claimed → nothing to check. Let it stop.
		dbg("no claims extracted — letting the agent stop")
		recordStop("no-claims", 0, nil)
		return StopResult{Handled: true, Obs: Observation{Outcome: "no-claims"}}
	}

	// 5. Verify each claim against git (the truth syscall). The git-log read is the
	//    boundary I/O — done ONCE and passed to the pure verifyDirect core.
	if runGitLog == nil {
		runGitLog = realGitLog
	}
	oneline := runGitLog(workspace)
	conv := readStampConvention(workspace)

	type failure struct{ plan, phase, source string }
	var failures []failure
	for _, c := range claims {
		v := verifyDirect(c.plan(), c.phase(), oneline, conv)
		recordVerify(v.supported, v.shipped, v.source)
		if !v.supported {
			// The native verify cannot own this claim (a non-generic convention or an
			// unported rung might fire). Delegate the WHOLE decision to Python so it
			// re-decides with the full rung set — never report a native NOT_SHIPPED
			// off an incomplete port (that would block a legitimate stop).
			dbg("verify abstained on %s %s — delegating to Python", c.plan(), c.phase())
			recordStop("delegate", len(claims), nil)
			return StopResult{Handled: false, Obs: Observation{Outcome: "delegate", ClaimsSeen: len(claims)}}
		}
		// actionable = c.confident or args.strict; --strict delegated, so it is just
		// c.confident. The non-strict extractor only returns marker claims (all
		// confident), so this is always true — kept explicit for fidelity.
		actionable := c.Confident()
		if !v.shipped && actionable {
			failures = append(failures, failure{c.plan(), c.phase(), v.source})
		}
	}

	if len(failures) > 0 {
		// Build the block reason byte-identically to cmd_hook_stop. bits is
		// "; ".join("{plan} {phase} (via {source})").
		parts := make([]string, len(failures))
		for i, f := range failures {
			parts[i] = fmt.Sprintf("%s %s (via %s)", f.plan, f.phase, f.source)
		}
		bits := strings.Join(parts, "; ")
		itThem := "it"
		if len(failures) != 1 {
			itThem = "them"
		}
		reason := fmt.Sprintf(
			"DOS verify: you claimed %s shipped, but git has no commit backing %s. "+
				"Land the commit (with the ship-stamp grammar) or correct the claim before stopping.",
			bits, itThem)
		block := map[string]any{"decision": "block", "reason": reason}
		dbg("BLOCK: %s", bits)
		sources := make([]string, len(failures))
		for i, f := range failures {
			sources[i] = f.source
		}
		recordStop("block", len(claims), sources)
		return StopResult{
			Handled: true,
			Stdout:  pyJSONDumps(block),
			Obs: Observation{
				Outcome: "block", ClaimsSeen: len(claims),
				BlockedPlan: failures[0].plan, BlockedPhase: failures[0].phase, VerifySource: failures[0].source,
			},
		}
	}

	// Every actionable claim verified. Let the agent stop.
	dbg("all %d claim(s) verified — letting the agent stop", len(claims))
	recordStop("all-verified", len(claims), nil)
	return StopResult{Handled: true, Obs: Observation{Outcome: "all-verified", ClaimsSeen: len(claims)}}
}

// realGitLog shells `git log --oneline -<window>` in the served workspace — the SAME
// call phase_shipped._build_log_cache / check_phase_shipped make (the
// _ONELINE_WINDOW = 4000 window). Returns the lines, or nil on any git failure (a
// git error in Python raises RuntimeError → check_phase_shipped returns shipped=False
// via "" — here a nil log means the direct scan finds nothing → a clean NOT_SHIPPED,
// the same not-shipped verdict; both then let-it-stop unless the claim was confident,
// in which case Python would also block off a not-shipped verdict, so a git failure
// is the one case the native path could over-block. To stay safe, an EMPTY log from a
// git error returns nil and verifyDirect reports source="none" shipped=false → the
// native path would BLOCK a confident claim. That is acceptable: it matches Python's
// behavior (a git failure makes Python's check_phase_shipped return shipped=False too,
// so Python ALSO blocks). Parity preserved.
const onelineWindow = 4000

func realGitLog(workspace string) []string {
	cmd := exec.Command("git", "log", "--oneline", fmt.Sprintf("-%d", onelineWindow))
	cmd.Dir = workspace
	out, err := cmd.Output()
	if err != nil {
		return nil
	}
	return splitLogLines(string(out))
}

// splitLogLines splits git output into lines, dropping a trailing empty line, matching
// Python's str.splitlines() over the subprocess stdout.
func splitLogLines(s string) []string {
	s = strings.ReplaceAll(s, "\r\n", "\n")
	lines := strings.Split(s, "\n")
	// Drop a trailing empty element from the final newline.
	for len(lines) > 0 && lines[len(lines)-1] == "" {
		lines = lines[:len(lines)-1]
	}
	return lines
}

// plan/phase accessors bridge the Claim field names (Plan/Phase) to verifyDirect's
// (plan, phase) signature without renaming the exported struct fields.
func (c Claim) plan() string  { return c.Plan }
func (c Claim) phase() string { return c.Phase }

package hook

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// The native `marker` decider — the Go port of `dos.marker_sensor` +
// `dos.loop_decide.wait_marker_budget` + `cli.cmd_hook_marker`. It is the wait-marker
// (keep-alive) budget: a `/loop`-style dispatch loop holds its turn open by emitting
// `claude -p` keep-alive markers, and each marker is a FULL assistant turn replaying
// the whole context out of prompt cache for zero forward work (session 4b4ff97c:
// 252 markers / ~$7.80, 91% of the run's cache_read). This hook refuses a marker once
// its budget is spent, BEFORE it is emitted (the pre-hoc sibling of the post-hoc
// `keepalive_poll` telemetry flag).
//
// POLARITY — the INVERSE of `stop`, stated sharply so the two never blur. A
// keep-alive marker is the loop CHOOSING NOT TO STOP (blocking its own Stop to keep
// waiting). So:
//
//   - budget REMAINS  (waitMarkerBudget.allow)  => record the marker + emit the CC
//     Stop dialect that HOLDS THE TURN OPEN: {"decision": "block", "reason": …}, exit 0
//     (CC's "keep working").
//   - budget EXHAUSTED (!allow)                  => emit NOTHING (an empty Stop output
//     is CC's "allow stop") so the loop ends its turn and waits on the real Bash
//     <task-notification>, which fires on the child's true exit regardless. The count
//     is NOT incremented past the cap (a refused marker was not emitted).
//
// `stop` BLOCKS a *false done* (claimed-ship vs git); this BLOCKS a *premature stop
// ONLY while the marker budget is unspent*, then gets out of the way. The two compose:
// a host can wire BOTH Stop hooks (stop first to refuse a false done, then this to
// bound the keep-alive polling of a true wait).
//
// Unlike `stop`, the native `marker` path OWNS its outcome and NEVER delegates to
// Python: delegating after reading the count would let the Python `||` fallback ALSO
// run and append a SECOND marker record (double-counting the budget). The boundary
// I/O (the per-session tally under .dos/markers/<sid>.jsonl) is here, at the edge;
// the verdict (waitMarkerBudget) is pure. Ported byte-faithfully so the emitted
// dialect AND the marker record match the Python path.

const (
	markerSchemaFamily  = "wait-marker"
	markerSchemaVersion = 1
	markersDirname      = "markers"
	defaultMaxMarkers   = 4 // the /dispatch-loop SKILL's per-run prose cap (loop_decide default)
)

// markerPathFor is `.dos/markers/<sid>.jsonl` under the workspace, or "" if the
// session sanitizes to empty — `marker_sensor.marker_path_for` (which rides
// cfg.paths.dot_dos). Reuses `safeSessionName` (posttool.go), the same host-authored
// session_id sanitizer the streams accumulator uses.
func markerPathFor(workspace, sessionID string) string {
	safe := safeSessionName(sessionID)
	if safe == "" {
		return ""
	}
	return filepath.Join(workspace, ".dos", markersDirname, safe+".jsonl")
}

// markerCount replays the session's marker tally into a COUNT — the Go port of
// `marker_sensor.marker_count`. Two distrust postures, byte-mirroring the Python read
// side (itself a copy of posttool_sensor.read_stream / intent_ledger.read_all):
//
//   - Torn-tail tolerance: an unparseable line (a crash mid-append, or a corrupt
//     mid-file line) is skipped — a half-written record is "didn't happen." The safe
//     direction is to UNDER-count (admit one more marker than strictly emitted), never
//     OVER-count (which would refuse a marker the loop was still entitled to) — the
//     conservative direction for an advisory cost guard.
//   - Schema gate (§6): a record whose `schema` tag is a non-additively-newer version
//     than understood is SKIPPED; an UNTAGGED (legacy) record is read permissively; a
//     WRONG_FAMILY record (a foreign line) is skipped.
//
// Returns 0 when the file is absent (no markers emitted yet — the budget's fresh
// floor). Only a record carrying `op == "MARKER"` is counted.
func markerCount(path string) int {
	if path == "" {
		return 0
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return 0
	}
	text := strings.ReplaceAll(string(data), "\r\n", "\n")
	text = strings.ReplaceAll(text, "\r", "\n")
	count := 0
	for _, line := range strings.Split(text, "\n") {
		s := strings.TrimSpace(line)
		if s == "" {
			continue
		}
		var obj map[string]any
		if err := json.Unmarshal([]byte(s), &obj); err != nil {
			continue // torn/corrupt line — "didn't happen" (under-count, never fabricate)
		}
		if !schemaReadableFamily(obj, markerSchemaFamily, markerSchemaVersion) {
			continue
		}
		if op, _ := obj["op"].(string); op != "MARKER" {
			continue // a record with no MARKER op is not a counted marker
		}
		count++
	}
	return count
}

// recordMarker appends ONE marker record to the session's tally + fsync — the Go port
// of `marker_sensor.record_marker` + `_marker_entry`. The record is a schema-tagged
// `{"op":"MARKER"}` line with the same additive optional fields the Python writer
// stamps: `reason` (the budget verdict's operator-facing line) and `run_id` (the
// correlation-spine join key, from CID_RUN_ID), present ONLY when known so a record
// without them reads back identically and the schema version does NOT bump. The line
// encoding is `json.dumps(e, sort_keys=True, default=str, ensure_ascii=False)` —
// pyJSONDumpsWAL, byte-for-byte. Best-effort: a write fault is swallowed (advisory —
// never crash a turn on the tally write; the caller degrades to "allow stop").
func recordMarker(path, reason, runID string) {
	defer func() { _ = recover() }()
	if path == "" {
		return
	}
	entry := map[string]any{
		"schema": map[string]any{"family": markerSchemaFamily, "version": markerSchemaVersion},
		"op":     "MARKER",
		"ts":     journalNowISO(),
	}
	// reason / run_id are additive optional fields — written ONLY when set (matching
	// Python's `if reason:` / `if run_id:`), so a bare record is byte-identical.
	if reason != "" {
		entry["reason"] = reason
	}
	if runID != "" {
		entry["run_id"] = runID
	}
	line := pyJSONDumpsWAL(entry) + "\n"
	if dir := dirOf(path); dir != "" {
		_ = os.MkdirAll(dir, 0o755)
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	if _, err := f.WriteString(line); err == nil {
		_ = f.Sync() // fsync — durable before we return, matching Python's os.fsync
	}
}

// schemaReadableFamily is the §6 gate (`durable_schema.classify`) parameterized by the
// expected family + understood version — the generalization of posttool.go's
// `schemaReadable` (which hardcodes the tool-stream family). READABLE (family matches
// AND version <= understood) or UNTAGGED (no schema key, or a malformed tag) proceed;
// a newer version or a wrong family is skipped. Kept separate from `schemaReadable` so
// the two accumulators stay independent (no shared-constant coupling).
func schemaReadableFamily(obj map[string]any, family string, understood int) bool {
	raw, present := obj["schema"]
	if !present {
		return true // UNTAGGED — read permissively (the tolerant side)
	}
	tag, ok := raw.(map[string]any)
	if !ok {
		return true // malformed tag — treat as untagged-permissive (Python's tolerant read)
	}
	fam, _ := tag["family"].(string)
	if fam != "" && fam != family {
		return false // WRONG_FAMILY — a foreign line, skip
	}
	if vf, ok := tag["version"].(float64); ok {
		if int(vf) > understood {
			return false // UNREADABLE_NEWER — never forge a count from a too-new record
		}
	}
	return true
}

// markerVerdict mirrors `dos.loop_decide.WaitMarkerDecision` — whether to emit one more
// keep-alive marker, the count to carry forward, and the operator-facing reason.
type markerVerdict struct {
	allow          bool
	markersEmitted int
	reason         string
}

// waitMarkerBudget is the pure verdict — the Go port of
// `loop_decide.wait_marker_budget`. PURE: the caller passes the running marker count,
// this returns the allow/refuse decision and the count to carry forward. Byte-faithful
// to the Python reason strings (they feed the durable record + the operator surface).
func waitMarkerBudget(markersEmitted, maxMarkers int) markerVerdict {
	if markersEmitted >= maxMarkers {
		return markerVerdict{
			allow:          false,
			markersEmitted: markersEmitted,
			reason: "wait-marker budget exhausted (" + itoa(markersEmitted) + "/" + itoa(maxMarkers) +
				") — each further marker replays full context out of cache for no work; wait on the " +
				"Bash task-notification, OC1's orphan sweep is the safety net",
		}
	}
	return markerVerdict{
		allow:          true,
		markersEmitted: markersEmitted + 1,
		reason:         "wait-marker " + itoa(markersEmitted+1) + "/" + itoa(maxMarkers) + " — turn held open",
	}
}

// markerBlockReason wraps the budget verdict's reason into the full block message
// `cmd_hook_marker` emits on the allow path (cli.py) — the operator-facing prose CC
// surfaces as the continuation reason. Byte-identical to the Python `reason` local.
func markerBlockReason(verdictReason string) string {
	return "DOS wait-marker budget: " + verdictReason + ". The keep-alive turn is held " +
		"open; continue waiting on the background task's completion signal rather " +
		"than re-polling. (This block is withdrawn once the budget is spent, at " +
		"which point you should end the turn and let the task-notification re-invoke " +
		"you.)"
}

// MarkerResult is the native marker outcome — Stdout is the block dialect to emit
// (empty when the budget is spent / any decline = let the agent stop). Handled is
// always true (the native path OWNS every marker outcome and NEVER delegates — see the
// file header: delegating would double-count the marker).
//
// Obs carries the observability projection (docs/276): the budget outcome
// (allow/refuse/unarmed) + the at-decision depth, for the durable record.
type MarkerResult struct {
	Handled bool
	Stdout  string
	Obs     Observation
}

// DecideMarker runs the native Stop-marker decider — the Go port of
// cli.cmd_hook_marker. It resolves the session tally, reads the running marker count
// (durable ground truth, not a flag the model threads through), asks the pure budget,
// and on ALLOW records the marker FIRST (so the count is durable even if the print is
// lost) then returns the block dialect; on REFUSE returns nothing. Any failure mode
// (no stdin, bad JSON, no session_id, an accumulator read/write fault) degrades to
// "emit nothing" = let the agent stop — the hook never traps a loop open on its own
// inability to read or write (advisory PDP, docs/99).
//
// `runID` is the CID_RUN_ID env join key (passed in by the dispatcher), stamped onto
// an emitted marker record exactly as the Python path does. `loop` arms the budget: it
// is the --loop flag OR a loop-scoping env (DOS_LOOP / a non-empty CID_RUN_ID), resolved
// by the caller. Without it the budget does NOT arm (docs/274: a Stop hook fires on every
// finished turn, so an unscoped budget forces keep-alive turns on ordinary turns).
//
// ⚠ CONFIG SPLIT (docs/274): the rich arming policy — a per-workspace `dos.toml [marker]`
// table that renames the arming env vars (arm_on_env), tunes the cap (max_streak), or
// toggles the stop_hook_active backstop — is a PYTHON-side concern (`dos.marker_gate` +
// `cli.cmd_hook_marker`). This native fast-path does NOT read dos.toml; it honors the two
// BUILT-IN arming signals (--loop, DOS_LOOP/CID_RUN_ID) and the default cap/backstop only.
// A host that renames its loop sentinel in [marker] either ALSO sets DOS_LOOP/CID_RUN_ID,
// or relies on the plugin's `dos-hook || python` fallback (the Python path applies the full
// [marker] policy). The pure budget arithmetic + emitted block bytes stay byte-identical
// across both paths (the parity corpus), so only the arming-CONFIG surface differs.
func DecideMarker(stdinBytes []byte, workspaceFlag, sessionFlag string, maxMarkers int, runID string, loop bool, debug io.Writer) MarkerResult {
	dbg := func(format string, a ...any) {
		if debug != nil {
			fmt.Fprintf(debug, "[dos-hook marker] "+format+"\n", a...)
		}
	}
	if maxMarkers <= 0 {
		maxMarkers = defaultMaxMarkers
	}

	// 1. Parse the event. A missing / unparseable stdin → emit nothing (allow stop) —
	//    never trap a loop open on our own inability to read.
	var top map[string]any
	if len(stdinBytes) > 0 {
		if err := json.Unmarshal(stdinBytes, &top); err != nil || top == nil {
			top = nil
			dbg("no/invalid stdin event — allow stop")
		}
	}

	// 2. Session identity: --session-id flag › the event's session_id. No id → no
	//    accumulator (an unkeyed tally cannot count a per-session marker run); allow stop.
	sessionID := sessionFlag
	if sessionID == "" && top != nil {
		if s, ok := top["session_id"].(string); ok {
			sessionID = s
		}
	}
	if strings.TrimSpace(sessionID) == "" {
		dbg("event has no session_id — no accumulator without an identity; allow stop")
		return MarkerResult{Handled: true}
	}

	// 2b. Respect Claude Code's own infinite-loop backstop (docs/274 Case C). The Stop
	//     event carries stop_hook_active:true when THIS stop is already being continued
	//     because a prior Stop hook blocked it. A wait-marker block FORCES another turn,
	//     so escalating an already-hook-continued stop is how a budget turns into a forced
	//     march — never re-block it.
	if top != nil {
		if active, ok := top["stop_hook_active"].(bool); ok && active {
			dbg("stop_hook_active — stop already hook-continued; do not re-block; allow stop")
			return MarkerResult{Handled: true}
		}
	}

	// 2c. ⚠ The TRIGGER guard (docs/274 — the load-bearing fix). A Stop hook fires when
	//     Claude finishes ANY turn (interactive included), NOT only on a keep-alive poll.
	//     The budget's polarity assumes a Stop == "the loop is about to poll again"; on a
	//     bare/global binding that is FALSE, so an unscoped budget MANUFACTURES the very
	//     keep-alive waste it exists to cap. So it arms ONLY when there is a positive loop
	//     signal (--loop / DOS_LOOP / CID_RUN_ID, folded into `loop` by the caller).
	//     Absent that, this is an ordinary interactive turn → emit nothing, allow stop.
	if !loop {
		dbg("no loop signal (--loop / DOS_LOOP / CID_RUN_ID) — ordinary turn, not a keep-alive poll; allow stop")
		recordMarkerVerdict(false, false, 0)
		return MarkerResult{Handled: true, Obs: Observation{Outcome: "unarmed"}}
	}

	// 3. Workspace: --workspace › the event's cwd › cwd (the cmd_hook_stop path), so
	//    the tally lands under the served root.
	wsArg := workspaceFlag
	if wsArg == "" && top != nil {
		if c, ok := top["cwd"].(string); ok {
			wsArg = c
		}
	}
	workspace := ResolveWorkspace(wsArg)
	markerPath := markerPathFor(workspace, sessionID)
	if markerPath == "" {
		dbg("session_id sanitizes to empty — no accumulator; allow stop")
		return MarkerResult{Handled: true}
	}

	// 4. Read the running marker count + ask the PURE budget.
	emitted := markerCount(markerPath)
	verdict := waitMarkerBudget(emitted, maxMarkers)
	dbg("emitted=%d max=%d allow=%v reason=%s", emitted, maxMarkers, verdict.allow, verdict.reason)

	if !verdict.allow {
		// Budget spent → stop polling. Emit NOTHING (CC's "allow stop"); the loop waits
		// on the real task-notification. Do NOT record (a refused marker was not emitted).
		recordMarkerVerdict(true, false, emitted)
		return MarkerResult{Handled: true, Obs: Observation{Outcome: "refuse", MarkerCount: emitted, MaxMarkers: maxMarkers}}
	}

	// Budget remains → hold the turn open one more marker. Record FIRST (so the count is
	// durable even if the print is lost), then emit the block dialect CC honors. A write
	// failure degrades to "allow stop" — never block on a tally we could not persist
	// (which would let the count desync and the loop spin). recordMarker is best-effort,
	// so we re-read the count to confirm the write landed before blocking.
	recordMarker(markerPath, verdict.reason, runID)
	if markerCount(markerPath) <= emitted {
		dbg("record_marker did not advance the count — allow stop (write likely failed)")
		recordMarkerVerdict(false, false, emitted)
		return MarkerResult{Handled: true, Obs: Observation{Outcome: "write-failed", MarkerCount: emitted, MaxMarkers: maxMarkers}}
	}
	recordMarkerVerdict(true, true, emitted)
	payload := map[string]any{"decision": "block", "reason": markerBlockReason(verdict.reason)}
	return MarkerResult{Handled: true, Stdout: pyJSONDumps(payload), Obs: Observation{Outcome: "allow", MarkerCount: emitted, MaxMarkers: maxMarkers}}
}

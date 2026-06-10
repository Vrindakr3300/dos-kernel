package hook

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// GHF2 — the native `posttool` decider, the Go port of `dos.posttool_sensor` +
// `dos.tool_stream.classify_stream`. The PostToolUse hook fires on Read|Bash|Grep|
// Glob, so it is the OTHER felt-latency surface (the matcher in hooks.json). It
// detects a REPEATING/STALLED tool-result loop (the env returning byte-identical
// results N times) and re-surfaces the value as `additionalContext` — it can never
// block (PostToolUse fires after the tool ran), so it is advisory-only.
//
// The boundary I/O (the per-session stream accumulator under .dos/streams/<sid>.jsonl)
// is here, at the edge; the verdict (classifyStream) is pure. Same shape as the
// Python module, ported byte-faithfully so the emitted dialect + the stream record
// match.

// Stream policy windows — `dos.tool_stream.StreamPolicy` defaults. The hot path
// uses the kernel defaults (a per-workspace `[tool_stream]` override is rare; a
// future phase can read it like the lane-journal path override).
const (
	streamRepeatN = 3 // ADVANCING -> REPEATING at this consecutive-identical run
	streamStallN  = 5 // REPEATING -> STALLED at this run
)

const (
	streamSchemaFamily  = "tool-stream"
	streamSchemaVersion = 1
	streamsDirname      = "streams"
)

var postResultKeys = []string{"tool_response", "tool_output"}

// streamStep mirrors `dos.tool_stream.StreamStep` — the agent-authored tool +
// args digest, the env-authored result digest (empty = no result, breaks a run).
type streamStep struct {
	toolName     string
	argsDigest   string
	resultDigest string // "" == None (no result)
}

// digest16 is the truncated SHA-256 (16 hex chars) `posttool_sensor._digest` uses
// — truncated to match `dos_solves_output_poll.py` so the live + offline digests
// agree.
func digest16(b []byte) string {
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])[:16]
}

// canonicalBytes is `posttool_sensor._canonical_bytes`: a string hashes as its own
// UTF-8 bytes; any other value as canonical JSON (sorted keys, ensure_ascii=False).
func canonicalBytes(v any) []byte {
	if s, ok := v.(string); ok {
		return []byte(s)
	}
	return []byte(pyJSONDumpsCompact(v))
}

// pyJSONDumpsCompact renders `json.dumps(v, sort_keys=True, default=str,
// ensure_ascii=False)` — NOTE: the digest in posttool_sensor uses json.dumps WITHOUT
// explicit separators, so it gets Python's DEFAULT `", "`/`": "` (the same as the
// WAL line). The digest is over these exact bytes, so Go must match: sorted keys,
// ensure_ascii=False, ", "/": " separators. pyJSONDumpsWAL already is exactly that.
func pyJSONDumpsCompact(v any) string { return pyJSONDumpsWAL(v) }

// stepFromEvent turns one PostToolUse event into a streamStep — the Go port of
// `posttool_sensor.step_from_event`. Returns (step, true) or (_, false) when there
// is no tool_name (nothing to record). args_digest is over {"input":…,"tool":…}
// (sorted keys put "input" before "tool"); result_digest is the env result, "" when
// absent (a None/missing result never matches → breaks a run).
func stepFromEvent(top map[string]any) (streamStep, bool) {
	tn, ok := top["tool_name"].(string)
	if !ok || tn == "" {
		return streamStep{}, false
	}
	toolInput := top["tool_input"]
	if toolInput == nil {
		toolInput = map[string]any{}
	}
	argsBlob := canonicalBytes(map[string]any{"tool": tn, "input": toolInput})
	argsDigest := digest16(argsBlob)

	present, result := resultFromEvent(top)
	resultDigest := ""
	if present {
		resultDigest = digest16(canonicalBytes(result))
	}
	return streamStep{toolName: tn, argsDigest: argsDigest, resultDigest: resultDigest}, true
}

// resultFromEvent reads the env result from tool_response › tool_output (the
// mandatory dual-read), treating an explicit null as absent — `_result_from_event`.
func resultFromEvent(top map[string]any) (bool, any) {
	for _, k := range postResultKeys {
		if v, ok := top[k]; ok && v != nil {
			return true, v
		}
	}
	return false, nil
}

// streamVerdict mirrors `dos.tool_stream.StreamVerdict`.
type streamVerdict struct {
	state     string // "ADVANCING" | "REPEATING" | "STALLED"
	repeatRun int
	repeated  *streamStep
	reason    string
}

// stepKey is the repeat-identity key, or ok=false when this step can never match
// (no result digest). The `ignore_tools` allow-list defaults empty on the hot path.
func (s streamStep) key() (string, bool) {
	if s.resultDigest == "" {
		return "", false
	}
	return strings.ToLower(s.toolName) + "\x00" + s.argsDigest + "\x00" + s.resultDigest, true
}

// trailingRun is `tool_stream._trailing_run`: the consecutive-identical-key run
// ending at the latest step + the repeated step.
func trailingRun(steps []streamStep) (int, *streamStep) {
	if len(steps) == 0 {
		return 0, nil
	}
	last := steps[len(steps)-1]
	lastKey, ok := last.key()
	if !ok {
		return 1, nil
	}
	run := 1
	for i := len(steps) - 2; i >= 0; i-- {
		k, ok := steps[i].key()
		if ok && k == lastKey {
			run++
		} else {
			break
		}
	}
	if run >= 2 {
		l := last
		return run, &l
	}
	return run, nil
}

// classifyStream is the pure verdict — `tool_stream.classify_stream`.
func classifyStream(steps []streamStep) streamVerdict {
	run, repeated := trailingRun(steps)
	switch {
	case run >= streamStallN:
		return streamVerdict{
			state: "STALLED", repeatRun: run, repeated: repeated,
			reason: "the same (tool, args, result) triple repeated " + itoa(run) +
				" consecutive times (>= stall " + itoa(streamStallN) + ") — the loop is " +
				"near-certainly doomed; the env returned identical bytes each time (no new information)",
		}
	case run >= streamRepeatN:
		return streamVerdict{
			state: "REPEATING", repeatRun: run, repeated: repeated,
			reason: "the same (tool, args, result) triple repeated " + itoa(run) +
				" consecutive times (>= repeat " + itoa(streamRepeatN) + ") — no new env-authored " +
				"bytes are entering the loop; re-surface the value the agent already received",
		}
	default:
		return streamVerdict{
			state: "ADVANCING", repeatRun: run, repeated: nil,
			reason: "trailing identical-run " + itoa(run) + " (< repeat " + itoa(streamRepeatN) +
				") — the tool stream is producing new env-authored bytes (or too short to judge a stall)",
		}
	}
}

// postWarnPayload renders a REPEATING/STALLED verdict as the exact CC PostToolUse
// WARN dialect — `posttool_sensor.warn_payload`. nil for ADVANCING (emit nothing).
func postWarnPayload(v streamVerdict) map[string]any {
	if v.state != "REPEATING" && v.state != "STALLED" {
		return nil
	}
	tool := "the same tool"
	digest := "(unknown)"
	if v.repeated != nil {
		tool = v.repeated.toolName
		if v.repeated.resultDigest != "" {
			digest = v.repeated.resultDigest
		}
	}
	text := "DOS tool_stream " + v.state + ": `" + tool + "` returned BYTE-IDENTICAL " +
		"results " + itoa(v.repeatRun) + " times in a row (env-authored digest " + digest +
		") — no new information is entering the loop. The value you already received has not " +
		"changed; do NOT re-issue the same call expecting a different answer. If you are " +
		"polling a background task / an async write, WAIT for its completion signal instead " +
		"of re-reading; otherwise USE the value you already hold and move on. (" + v.reason + ")"
	return map[string]any{
		"hookSpecificOutput": map[string]any{
			"hookEventName":     "PostToolUse",
			"additionalContext": text,
		},
	}
}

// ---------------------------------------------------------------------------
// Boundary I/O — the per-session stream accumulator (.dos/streams/<sid>.jsonl).
// Byte-mirrors posttool_sensor.append_step / read_stream.
// ---------------------------------------------------------------------------

// safeSessionName sanitizes the host-authored session_id into a filename stem (or
// "" to skip) — `posttool_sensor._safe_session_name`. Keeps only alnum/-/_ so a
// hostile id can never escape the streams dir.
func safeSessionName(sessionID string) string {
	var b strings.Builder
	for _, c := range sessionID {
		if (c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '-' || c == '_' {
			b.WriteRune(c)
		}
	}
	return b.String()
}

// streamPathFor is `.dos/streams/<sid>.jsonl` under the workspace, or "" if the
// session sanitizes to empty. The streams dir rides the `.dos/` home, matching
// `posttool_sensor.stream_path_for` (which uses cfg.paths.dot_dos).
func streamPathFor(workspace, sessionID string) string {
	safe := safeSessionName(sessionID)
	if safe == "" {
		return ""
	}
	return filepath.Join(workspace, ".dos", streamsDirname, safe+".jsonl")
}

// readStream replays the session's stream log into the steps — the Go port of
// `posttool_sensor.read_stream`, with the §6 schema gate: a record whose schema
// family matches but version > understood is SKIPPED (a too-new record never forges
// a repeat); an untagged record is read permissively as v1; a wrong-family or
// unparseable line is skipped. A missing file → empty (ADVANCING floor).
func readStream(path string) []streamStep {
	if path == "" {
		return nil
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	text := strings.ReplaceAll(string(data), "\r\n", "\n")
	text = strings.ReplaceAll(text, "\r", "\n")
	var steps []streamStep
	for _, line := range strings.Split(text, "\n") {
		s := strings.TrimSpace(line)
		if s == "" {
			continue
		}
		var obj map[string]any
		if err := json.Unmarshal([]byte(s), &obj); err != nil {
			continue // torn/corrupt line — skip (under-count, never fabricate)
		}
		if !schemaReadable(obj) {
			continue
		}
		tn, ok1 := obj["tool_name"].(string)
		ad, ok2 := obj["args_digest"].(string)
		if !ok1 || !ok2 {
			continue // no identity — not a comparable step
		}
		rd := ""
		if v, ok := obj["result_digest"].(string); ok {
			rd = v
		}
		steps = append(steps, streamStep{toolName: tn, argsDigest: ad, resultDigest: rd})
	}
	return steps
}

// schemaReadable is the §6 gate (`durable_schema.classify`): READABLE (family ==
// tool-stream AND version <= understood) or UNTAGGED (no schema key) proceed; a
// newer version or a wrong family is skipped.
func schemaReadable(obj map[string]any) bool {
	raw, present := obj["schema"]
	if !present {
		return true // UNTAGGED — read permissively as v1 (the tolerant side)
	}
	tag, ok := raw.(map[string]any)
	if !ok {
		return true // malformed tag — treat as untagged-permissive (Python's tolerant read)
	}
	fam, _ := tag["family"].(string)
	if fam != "" && fam != streamSchemaFamily {
		return false // WRONG_FAMILY — a foreign line, skip
	}
	if vf, ok := tag["version"].(float64); ok {
		if int(vf) > streamSchemaVersion {
			return false // UNREADABLE_NEWER — never forge a repeat from a too-new record
		}
	}
	return true
}

// appendStep appends ONE step to the session stream log + fsync — the Go port of
// `posttool_sensor.append_step` (schema-tagged record, sorted-key ensure_ascii=False
// line, O_APPEND, fsync). The `verdict_state` join-field is stamped only on a firing
// (REPEATING/STALLED), matching the docs/179 additive record.
func appendStep(path string, s streamStep, stepIndex int, verdictState, runID string) {
	defer func() { _ = recover() }()
	if path == "" {
		return
	}
	entry := map[string]any{
		"schema":        map[string]any{"family": streamSchemaFamily, "version": streamSchemaVersion},
		"op":            "STEP",
		"tool_name":     s.toolName,
		"args_digest":   s.argsDigest,
		"result_digest": resultDigestJSON(s.resultDigest),
		"step_index":    stepIndex,
		"ts":            journalNowISO(),
	}
	// run_id / verdict_state are the docs/179 additive firing-join fields — written
	// ONLY when set (a fired step), so a non-firing record is byte-identical to v1.
	if runID != "" {
		entry["run_id"] = runID
	}
	if verdictState != "" {
		entry["verdict_state"] = verdictState
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
		_ = f.Sync()
	}
}

// resultDigestJSON returns the digest string, or nil (JSON null) when absent —
// matching Python writing result_digest=None as JSON null (and reading it back as
// None / a run-break).
func resultDigestJSON(rd string) any {
	if rd == "" {
		return nil
	}
	return rd
}

// itoa renders an int the way Python's str(int) does (no separators) — used in the
// WARN prose + the reason strings, which must match the Python byte-for-byte.
func itoa(n int) string { return strconv.Itoa(n) }

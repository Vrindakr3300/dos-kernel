package hook

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// --- the pure budget verdict (loop_decide.wait_marker_budget) ---

func TestWaitMarkerBudgetBoundary(t *testing.T) {
	// allow up to but not including max; the boundary is `>=` (0..3 allow at max=4, 4 refuses).
	for _, tc := range []struct {
		emitted, max int
		wantAllow    bool
		wantCarry    int
	}{
		{0, 4, true, 1},
		{3, 4, true, 4},
		{4, 4, false, 4}, // budget exhausted — carry stays put (a refused marker was not emitted)
		{5, 4, false, 5},
		{0, 1, true, 1},
		{1, 1, false, 1},
	} {
		v := waitMarkerBudget(tc.emitted, tc.max)
		if v.allow != tc.wantAllow || v.markersEmitted != tc.wantCarry {
			t.Fatalf("waitMarkerBudget(%d,%d) = (allow=%v carry=%d), want (allow=%v carry=%d)",
				tc.emitted, tc.max, v.allow, v.markersEmitted, tc.wantAllow, tc.wantCarry)
		}
	}
}

func TestWaitMarkerBudgetReasonBytes(t *testing.T) {
	// The reason strings are durable (they feed the record + the operator surface), so
	// they must match the Python loop_decide.wait_marker_budget byte-for-byte.
	allow := waitMarkerBudget(1, 4)
	if allow.reason != "wait-marker 2/4 — turn held open" {
		t.Fatalf("allow reason drift: %q", allow.reason)
	}
	refuse := waitMarkerBudget(4, 4)
	wantRefuse := "wait-marker budget exhausted (4/4) — each further marker replays full " +
		"context out of cache for no work; wait on the Bash task-notification, OC1's orphan " +
		"sweep is the safety net"
	if refuse.reason != wantRefuse {
		t.Fatalf("refuse reason drift:\n got: %q\nwant: %q", refuse.reason, wantRefuse)
	}
}

// --- the accumulator (marker_sensor.marker_count / record_marker) ---

func tmpMarkerPath(t *testing.T) string {
	t.Helper()
	return filepath.Join(t.TempDir(), ".dos", markersDirname, "sess.jsonl")
}

func TestMarkerCountAbsentFileIsZero(t *testing.T) {
	if n := markerCount(filepath.Join(t.TempDir(), "nope.jsonl")); n != 0 {
		t.Fatalf("absent file must count 0, got %d", n)
	}
	if n := markerCount(""); n != 0 {
		t.Fatalf("empty path must count 0, got %d", n)
	}
}

func TestRecordThenCountRoundTrips(t *testing.T) {
	p := tmpMarkerPath(t)
	for i := 0; i < 3; i++ {
		recordMarker(p, "wait-marker x — turn held open", "")
	}
	if n := markerCount(p); n != 3 {
		t.Fatalf("3 records must count 3, got %d", n)
	}
}

func TestRecordMarkerWritesSchemaTaggedMarkerOp(t *testing.T) {
	p := tmpMarkerPath(t)
	recordMarker(p, "r", "run-7")
	data, err := os.ReadFile(p)
	if err != nil {
		t.Fatalf("read back: %v", err)
	}
	var obj map[string]any
	if err := json.Unmarshal([]byte(strings.TrimSpace(string(data))), &obj); err != nil {
		t.Fatalf("record is not valid JSON: %v (%q)", err, data)
	}
	if obj["op"] != "MARKER" {
		t.Fatalf("record op must be MARKER, got %v", obj["op"])
	}
	tag, _ := obj["schema"].(map[string]any)
	if tag == nil || tag["family"] != markerSchemaFamily {
		t.Fatalf("record must carry the wait-marker schema family, got %v", obj["schema"])
	}
	if obj["reason"] != "r" || obj["run_id"] != "run-7" {
		t.Fatalf("reason/run_id additive fields must round-trip, got reason=%v run_id=%v", obj["reason"], obj["run_id"])
	}
	if _, ok := obj["ts"]; !ok {
		t.Fatalf("record must carry a ts stamp")
	}
}

func TestRecordMarkerOmitsEmptyAdditiveFields(t *testing.T) {
	// reason="" / run_id="" are NOT written (matching Python's `if reason:` / `if run_id:`),
	// so a bare record is byte-identical to v1 and the schema version never bumps.
	p := tmpMarkerPath(t)
	recordMarker(p, "", "")
	data, _ := os.ReadFile(p)
	var obj map[string]any
	_ = json.Unmarshal([]byte(strings.TrimSpace(string(data))), &obj)
	if _, ok := obj["reason"]; ok {
		t.Fatalf("empty reason must be omitted, got %v", obj["reason"])
	}
	if _, ok := obj["run_id"]; ok {
		t.Fatalf("empty run_id must be omitted, got %v", obj["run_id"])
	}
}

func TestMarkerCountTornTailTolerant(t *testing.T) {
	// A torn / corrupt final line is "didn't happen" — under-count, never fabricate.
	p := tmpMarkerPath(t)
	recordMarker(p, "a", "")
	recordMarker(p, "b", "")
	f, _ := os.OpenFile(p, os.O_WRONLY|os.O_APPEND, 0o644)
	_, _ = f.WriteString(`{"op":"MARKER","schema":{"family":"wait-marker",` + "\n") // torn line
	_ = f.Close()
	if n := markerCount(p); n != 2 {
		t.Fatalf("torn tail must be skipped (count 2), got %d", n)
	}
}

func TestMarkerCountSchemaGate(t *testing.T) {
	p := tmpMarkerPath(t)
	lines := []string{
		`{"op":"MARKER","schema":{"family":"wait-marker","version":1}}`,       // READABLE
		`{"op":"MARKER"}`,                                                      // UNTAGGED — read permissively
		`{"op":"MARKER","schema":{"family":"wait-marker","version":9}}`,       // UNREADABLE_NEWER — skip
		`{"op":"MARKER","schema":{"family":"tool-stream","version":1}}`,       // WRONG_FAMILY — skip
		`{"op":"STEP","schema":{"family":"wait-marker","version":1}}`,         // not a MARKER op — skip
	}
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(strings.Join(lines, "\n")+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if n := markerCount(p); n != 2 {
		t.Fatalf("schema gate: only the READABLE + UNTAGGED MARKER records count (2), got %d", n)
	}
}

// --- the decider (cli.cmd_hook_marker) ---

func markerEvent(sessionID string) []byte {
	b, _ := json.Marshal(map[string]any{"hook_event_name": "Stop", "session_id": sessionID})
	return b
}

func TestDecideMarkerNoSessionAllowsStop(t *testing.T) {
	// No session_id → no accumulator → emit nothing (allow stop).
	res := DecideMarker([]byte(`{"hook_event_name":"Stop"}`), t.TempDir(), "", 4, "", false, nil)
	if res.Stdout != "" {
		t.Fatalf("no session_id must emit nothing, got %q", res.Stdout)
	}
}

func TestDecideMarkerBadStdinAllowsStop(t *testing.T) {
	if res := DecideMarker([]byte("not json"), t.TempDir(), "", 4, "", false, nil); res.Stdout != "" {
		t.Fatalf("bad stdin must emit nothing, got %q", res.Stdout)
	}
	if res := DecideMarker(nil, t.TempDir(), "", 4, "", false, nil); res.Stdout != "" {
		t.Fatalf("empty stdin must emit nothing, got %q", res.Stdout)
	}
}

// The headline property: repeated DecideMarker calls under one session BLOCK while the
// budget is unspent then ALLOW STOP at the cap — and the durable count is what bounds
// it (a marker is recorded on each block, refused at the cap), so the loop cannot poll
// past its budget. This is also the double-count guard: each native call appends EXACTLY
// one record (the native path owns the outcome and never delegates), so N blocks leave
// N records and the (N+1)th refuses.
func TestDecideMarkerBudgetSequenceOwnsAndBounds(t *testing.T) {
	ws := t.TempDir()
	const sid = "sequence-session"
	const max = 4
	// Markers 1..4 are allowed (block, turn held open); the 5th is refused (allow stop).
	for i := 1; i <= max; i++ {
		res := DecideMarker(markerEvent(sid), ws, "", max, "", true, nil)
		if res.Stdout == "" {
			t.Fatalf("marker %d/%d should BLOCK (hold the turn open), got empty stdout", i, max)
		}
		var obj map[string]any
		if err := json.Unmarshal([]byte(strings.TrimSpace(res.Stdout)), &obj); err != nil {
			t.Fatalf("marker %d: block dialect is not valid JSON: %v (%q)", i, err, res.Stdout)
		}
		if obj["decision"] != "block" {
			t.Fatalf("marker %d: block dialect must be decision=block, got %v", i, obj["decision"])
		}
		reason, _ := obj["reason"].(string)
		if !strings.Contains(reason, "DOS wait-marker budget") {
			t.Fatalf("marker %d: block reason missing the budget prose: %q", i, reason)
		}
	}
	// The 5th call: budget spent → emit nothing (allow stop).
	if res := DecideMarker(markerEvent(sid), ws, "", max, "", true, nil); res.Stdout != "" {
		t.Fatalf("marker %d/%d should ALLOW STOP (emit nothing), got %q", max+1, max, res.Stdout)
	}
	// Exactly `max` records on disk — one per allowed marker, none for the refused one
	// (the double-count guard: the native path never delegated, so Python never appended
	// a second record).
	p := markerPathFor(ws, sid)
	if n := markerCount(p); n != max {
		t.Fatalf("exactly %d markers should be recorded (one per block, none on refuse), got %d", max, n)
	}
}

func TestDecideMarkerOrdinaryTurnWithoutLoopAllowsStop(t *testing.T) {
	// ⚠ docs/274 — the load-bearing fix, ported to Go. A Stop hook fires on EVERY
	// finished turn, not only a keep-alive poll. Without a loop signal (loop=false) the
	// budget must NOT arm — an ordinary turn allows the stop (empty stdout) and records
	// nothing — even though the budget is fresh and would otherwise block.
	ws := t.TempDir()
	const sid = "ordinary-session"
	res := DecideMarker(markerEvent(sid), ws, "", 4, "", false, nil)
	if res.Stdout != "" {
		t.Fatalf("an ordinary turn (loop=false) must allow stop, got %q", res.Stdout)
	}
	if n := markerCount(markerPathFor(ws, sid)); n != 0 {
		t.Fatalf("an unarmed turn must record no marker, got count %d", n)
	}
}

func TestDecideMarkerStopHookActiveNeverReBlocks(t *testing.T) {
	// docs/274 Case C — honor Claude Code's own infinite-loop backstop. A Stop event
	// carrying stop_hook_active:true is ALREADY being continued by a prior hook; the
	// marker hook must not escalate it, even inside a loop with budget remaining.
	ws := t.TempDir()
	ev, _ := json.Marshal(map[string]any{
		"hook_event_name": "Stop", "session_id": "active-session", "stop_hook_active": true,
	})
	res := DecideMarker(ev, ws, "", 4, "", true, nil) // loop=true, but stop_hook_active wins
	if res.Stdout != "" {
		t.Fatalf("an already-hook-continued stop must not be re-blocked, got %q", res.Stdout)
	}
}

func TestDecideMarkerDefaultMaxIsFour(t *testing.T) {
	// maxMarkers<=0 applies the verb default (4) — matching the SKILL's per-run cap.
	ws := t.TempDir()
	const sid = "default-max"
	for i := 1; i <= 4; i++ {
		if res := DecideMarker(markerEvent(sid), ws, "", 0, "", true, nil); res.Stdout == "" {
			t.Fatalf("with default max, marker %d should block", i)
		}
	}
	if res := DecideMarker(markerEvent(sid), ws, "", 0, "", true, nil); res.Stdout != "" {
		t.Fatalf("with default max=4, the 5th marker should allow stop, got %q", res.Stdout)
	}
}

func TestDecideMarkerBlockReasonByteExact(t *testing.T) {
	// The full block reason (the operator-facing continuation prose) must match the
	// Python cmd_hook_marker byte-for-byte: budget-reason wrapped in the held-open prose.
	ws := t.TempDir()
	res := DecideMarker(markerEvent("bytes"), ws, "", 4, "", true, nil)
	var obj map[string]any
	_ = json.Unmarshal([]byte(strings.TrimSpace(res.Stdout)), &obj)
	want := "DOS wait-marker budget: wait-marker 1/4 — turn held open. The keep-alive turn " +
		"is held open; continue waiting on the background task's completion signal rather " +
		"than re-polling. (This block is withdrawn once the budget is spent, at which point " +
		"you should end the turn and let the task-notification re-invoke you.)"
	if obj["reason"] != want {
		t.Fatalf("block reason drift:\n got: %q\nwant: %q", obj["reason"], want)
	}
}

func TestDecideMarkerHostileSessionIDCannotEscape(t *testing.T) {
	// A path-traversal session_id sanitizes away every separator, so the tally can never
	// escape .dos/markers/ — same guard as the streams accumulator.
	ws := t.TempDir()
	res := DecideMarker(markerEvent("../../etc/passwd"), ws, "", 4, "", true, nil)
	// It still decides (the sanitized stem is non-empty: "etcpasswd"), and the record
	// lands strictly under the workspace's .dos/markers.
	if res.Stdout == "" {
		t.Fatalf("a sanitizable id should still decide")
	}
	p := markerPathFor(ws, "../../etc/passwd")
	if !strings.HasPrefix(p, filepath.Join(ws, ".dos", markersDirname)) {
		t.Fatalf("hostile session_id escaped the markers dir: %q", p)
	}
}

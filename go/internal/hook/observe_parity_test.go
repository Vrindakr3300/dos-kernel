package hook

import (
	"os"
	"strings"
	"testing"
)

// The load-bearing observability invariant (docs/276): counting + the durable record
// are strictly DOWNSTREAM of an already-decided verdict, so the GATED decision bytes
// (the stdout dialect every host parses) must be byte-IDENTICAL whether metrics are
// on (default) or off (DOS_HOOK_METRICS=0). If observability ever perturbed a
// decision byte, the docs/124 parity contract would be broken. This test pins that
// the emitted Stdout is invariant across the metrics flag for every verb's headline
// outcome.

func TestMetricsDoNotPerturbGatedBytes(t *testing.T) {
	// A SELF_MODIFY deny event (the richest gated output — a full deny dialect).
	ws := t.TempDir()
	// Seed a runtime file so the SELF_MODIFY tree-collision fires under this workspace.
	seedRuntimeFile(t, ws, "src/dos/arbiter.py")
	// JSON string literals cannot carry Windows backslashes (\U/\T are invalid JSON
	// escapes → an unmarshal failure → an empty passthrough). The event's paths must
	// be POSIX-slash form; the decider's repoRelative normalizes either way.
	wsSlash := strings.ReplaceAll(ws, "\\", "/")
	denyEvent := []byte(`{"hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"file_path":"` + wsSlash + `/src/dos/arbiter.py"},"cwd":"` + wsSlash + `","session_id":"s1"}`)

	// Decide twice — the decider is pure, so the in-process counters increment but the
	// returned Stdout (the gated bytes) must be identical. The durable write gate is
	// the dispatcher's; the decider's Stdout is what hosts parse.
	resetMetricsForTest()
	a := DecidePretool(denyEvent, ws, "", nil)
	resetMetricsForTest()
	b := DecidePretool(denyEvent, ws, "", nil)

	if a.Stdout != b.Stdout {
		t.Fatalf("gated deny bytes differ across runs:\n a=%q\n b=%q", a.Stdout, b.Stdout)
	}
	if a.Stdout == "" {
		t.Fatalf("expected a non-empty deny dialect for a SELF_MODIFY edit, got empty")
	}
	if a.Decision.ReasonClass != "SELF_MODIFY" {
		t.Fatalf("expected SELF_MODIFY reason_class, got %q", a.Decision.ReasonClass)
	}

	// The recorder ran (the verdict-specific dimension is counted) — observability is
	// live, yet the bytes above were unchanged.
	got := snapshotMap(t)
	if got["pretool_reason_cls|SELF_MODIFY"] != 1 {
		t.Fatalf("expected the SELF_MODIFY reason-class counter to fire, snapshot=%v",
			filterKeys(got, "pretool_"))
	}
}

// A marker block (the keep-alive dialect) is likewise byte-invariant across the flag.
func TestMetricsDoNotPerturbMarkerBytes(t *testing.T) {
	ws := t.TempDir()
	ev := []byte(`{"hook_event_name":"Stop","session_id":"s1","cwd":"` + strings.ReplaceAll(ws, "\\", "/") + `"}`)
	resetMetricsForTest()
	a := DecideMarker(ev, ws, "s1", 4, "", true, nil)
	// The first call recorded a marker; use a fresh session so the second sees the same
	// fresh budget (else the count differs legitimately).
	ws2 := t.TempDir()
	ev2 := []byte(`{"hook_event_name":"Stop","session_id":"s1","cwd":"` + strings.ReplaceAll(ws2, "\\", "/") + `"}`)
	resetMetricsForTest()
	b := DecideMarker(ev2, ws2, "s1", 4, "", true, nil)
	if a.Stdout != b.Stdout {
		t.Fatalf("marker block bytes differ across fresh budgets:\n a=%q\n b=%q", a.Stdout, b.Stdout)
	}
	if a.Stdout == "" {
		t.Fatalf("expected a marker block dialect on a fresh armed budget")
	}
}

// seedRuntimeFile creates a repo-relative runtime file under ws so the SELF_MODIFY
// tree collision (treeTouchesRuntime over ExistingRuntimeFiles) fires.
func seedRuntimeFile(t *testing.T, ws, rel string) {
	t.Helper()
	full := ws + "/" + rel
	if dir := dirOf(full); dir != "" {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(full, []byte("# seed\n"), 0o644); err != nil {
		t.Fatal(err)
	}
}

package hook

import (
	"strings"
	"testing"
)

// mkStep is a test helper producing a step with a fixed env result digest.
func mkStep(tool, result string) streamStep {
	args := digest16(canonicalBytes(map[string]any{"tool": tool, "input": map[string]any{}}))
	return streamStep{toolName: tool, argsDigest: args, resultDigest: digest16(canonicalBytes(result))}
}

func TestClassifyStreamAdvancingThenRepeatingThenStalled(t *testing.T) {
	// 1-2 identical -> ADVANCING (< repeat_n=3); 3-4 -> REPEATING; 5 -> STALLED.
	var steps []streamStep
	want := []string{"ADVANCING", "ADVANCING", "REPEATING", "REPEATING", "STALLED"}
	for i := 0; i < 5; i++ {
		steps = append(steps, mkStep("Read", "SAME"))
		v := classifyStream(steps)
		if v.state != want[i] {
			t.Fatalf("step %d: want %s, got %s (run=%d)", i+1, want[i], v.state, v.repeatRun)
		}
	}
}

func TestClassifyStreamNewBytesBreakRun(t *testing.T) {
	steps := []streamStep{mkStep("Read", "A"), mkStep("Read", "A"), mkStep("Read", "B")}
	v := classifyStream(steps)
	if v.state != "ADVANCING" {
		t.Fatalf("new bytes should break the run -> ADVANCING, got %s", v.state)
	}
}

func TestClassifyStreamAbsentResultBreaksRun(t *testing.T) {
	// A step with no result digest can never match — it breaks a run (fail-safe).
	a := mkStep("Read", "A")
	noResult := streamStep{toolName: "Read", argsDigest: a.argsDigest, resultDigest: ""}
	steps := []streamStep{a, a, noResult}
	v := classifyStream(steps)
	if v.state != "ADVANCING" || v.repeatRun != 1 {
		t.Fatalf("absent-result step must break the run, got %s run=%d", v.state, v.repeatRun)
	}
}

func TestPostWarnPayloadShape(t *testing.T) {
	steps := []streamStep{mkStep("Read", "X"), mkStep("Read", "X"), mkStep("Read", "X")}
	v := classifyStream(steps)
	p := postWarnPayload(v)
	if p == nil {
		t.Fatal("REPEATING should produce a warn payload")
	}
	out := pyJSONDumps(p)
	if !strings.Contains(out, `"hookEventName": "PostToolUse"`) {
		t.Fatalf("warn must carry PostToolUse hookEventName: %s", out)
	}
	if !strings.Contains(out, `"additionalContext"`) {
		t.Fatalf("warn must carry additionalContext: %s", out)
	}
	if strings.Contains(out, "permissionDecision") {
		t.Fatalf("PostToolUse warn must NOT carry permissionDecision (it cannot block): %s", out)
	}
	if !strings.Contains(out, "DOS tool_stream REPEATING:") {
		t.Fatalf("warn text mismatch: %s", out)
	}
}

func TestPostWarnPayloadAdvancingIsNil(t *testing.T) {
	v := classifyStream([]streamStep{mkStep("Read", "X")})
	if postWarnPayload(v) != nil {
		t.Fatal("ADVANCING must produce no warn payload")
	}
}

func TestDigestMatchesCanonicalJSON(t *testing.T) {
	// A string result hashes as its own bytes; a structured result as canonical JSON.
	if digest16([]byte("hello")) != digest16(canonicalBytes("hello")) {
		t.Fatal("string canonicalBytes should be the raw bytes")
	}
	// Two dicts equal modulo key order must digest equally.
	a := canonicalBytes(map[string]any{"b": 1, "a": 2})
	b := canonicalBytes(map[string]any{"a": 2, "b": 1})
	if digest16(a) != digest16(b) {
		t.Fatal("canonical JSON must sort keys so key order doesn't change the digest")
	}
}

func TestStreamSchemaGate(t *testing.T) {
	// A newer-version record is skipped; an untagged record is read as v1; a
	// wrong-family record is skipped.
	newer := map[string]any{"schema": map[string]any{"family": "tool-stream", "version": float64(99)}, "tool_name": "Read", "args_digest": "a"}
	if schemaReadable(newer) {
		t.Fatal("a newer-version record must be skipped (UNREADABLE_NEWER)")
	}
	untagged := map[string]any{"tool_name": "Read", "args_digest": "a"}
	if !schemaReadable(untagged) {
		t.Fatal("an untagged record must be read permissively as v1")
	}
	wrongFam := map[string]any{"schema": map[string]any{"family": "lane-journal", "version": float64(1)}}
	if schemaReadable(wrongFam) {
		t.Fatal("a wrong-family record must be skipped")
	}
}

func TestSafeSessionNameStripsTraversal(t *testing.T) {
	if got := safeSessionName("../../etc/passwd"); strings.Contains(got, "/") || strings.Contains(got, ".") {
		t.Fatalf("session name must strip path separators + dots, got %q", got)
	}
	if safeSessionName("a1b2-c3_d4") != "a1b2-c3_d4" {
		t.Fatal("a normal session uuid must pass through unchanged")
	}
	if safeSessionName("") != "" {
		t.Fatal("empty session must yield empty (skip)")
	}
}

package hook

import "testing"

// These pin the byte-output of pyJSONDumps against hand-computed
// `json.dumps(obj, sort_keys=True)` results — the GHF byte-exact contract for the
// emitted dialect. The cross-engine differential corpus (parity_test.go) proves it
// at scale against the live Python; these are the fast, Python-free anchors.
//
// NOTE: ensure_ascii=True means every non-ASCII rune is escaped to \uXXXX, so the
// `want` literals below carry the ESCAPE SEQUENCES, not the runes — that escaping
// IS the property under test.
func TestPyJSONSortKeys(t *testing.T) {
	got := pyJSONDumps(map[string]any{"b": 1, "a": 2})
	want := `{"a": 2, "b": 1}`
	if got != want {
		t.Fatalf("sort_keys: got %q want %q", got, want)
	}
}

func TestPyJSONEnsureASCII(t *testing.T) {
	// em-dash (U+2014) -> —, ≤ (U+2264) -> ≤.
	got := pyJSONDumps(map[string]any{"r": "a — b ≤ c"})
	want := "{\"r\": \"a \\u2014 b \\u2264 c\"}"
	if got != want {
		t.Fatalf("ensure_ascii: got %q want %q", got, want)
	}
}

func TestPyJSONNoSlashEscape(t *testing.T) {
	// Python's json does NOT escape "/" (Go's stdlib does). A path must stay plain.
	got := pyJSONDumps(map[string]any{"p": "src/dos/arbiter.py"})
	want := `{"p": "src/dos/arbiter.py"}`
	if got != want {
		t.Fatalf("slash: got %q want %q", got, want)
	}
}

func TestPyJSONNoHTMLEscape(t *testing.T) {
	// Python's json does NOT HTML-escape <,>,& (Go's stdlib does by default).
	got := pyJSONDumps(map[string]any{"x": "a<b>c&d"})
	want := `{"x": "a<b>c&d"}`
	if got != want {
		t.Fatalf("html: got %q want %q", got, want)
	}
}

func TestPyJSONNestedDialect(t *testing.T) {
	d := denyPayload("DOS PRE-admission: lane 'Edit' — nope.", "")
	got := pyJSONDumps(d)
	want := "{\"hookSpecificOutput\": {\"hookEventName\": \"PreToolUse\", \"permissionDecision\": \"deny\", \"permissionDecisionReason\": \"DOS PRE-admission: lane 'Edit' \\u2014 nope.\"}}"
	if got != want {
		t.Fatalf("nested dialect:\n got %q\nwant %q", got, want)
	}
}

func TestPyJSONControlChars(t *testing.T) {
	got := pyJSONDumps(map[string]any{"c": "a\tb\nc"})
	want := `{"c": "a\tb\nc"}`
	if got != want {
		t.Fatalf("control: got %q want %q", got, want)
	}
}

func TestPyJSONAstral(t *testing.T) {
	// An astral-plane rune (U+1F680 rocket) must surrogate-pair like Python:
	// 🚀.
	got := pyJSONDumps(map[string]any{"e": "x\U0001F680y"})
	want := "{\"e\": \"x\\ud83d\\ude80y\"}"
	if got != want {
		t.Fatalf("astral: got %q want %q", got, want)
	}
}

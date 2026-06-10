package hook

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// verifyCase mirrors one line of parity/corpus_verify.jsonl — a hermetic differential
// case for the native verify direct rung (docs/125 native stop). The corpus carries
// the EXACT git-log oneline window the Python grep rung scanned + Python's
// (shipped, sha, via, source) verdict over it. The Go test replays verifyDirect over
// the same injected window and asserts the projection matches — or, for a rung the
// native port deliberately abstains on (anything other than `direct`), that the Go
// verdict is `supported=false`.
type verifyCase struct {
	Name     string   `json:"name"`
	Plan     string   `json:"plan"`
	Phase    string   `json:"phase"`
	Oneline  []string `json:"oneline"`
	PyShipped bool    `json:"py_shipped"`
	PySha    string   `json:"py_sha"`
	PyVia    string   `json:"py_via"`
	PySource string   `json:"py_source"`
}

func loadVerifyCorpus(t *testing.T) []verifyCase {
	t.Helper()
	path := filepath.Join("parity", "corpus_verify.jsonl")
	f, err := os.Open(path)
	if err != nil {
		t.Fatalf("open verify corpus %s: %v (run `python go/internal/hook/parity/gen_corpus_verify.py`)", path, err)
	}
	defer f.Close()
	var cases []verifyCase
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<24), 1<<24) // the real-history windows are large
	for sc.Scan() {
		line := sc.Bytes()
		if len(line) == 0 {
			continue
		}
		var c verifyCase
		if err := json.Unmarshal(line, &c); err != nil {
			t.Fatalf("verify corpus line unmarshal: %v", err)
		}
		cases = append(cases, c)
	}
	if err := sc.Err(); err != nil {
		t.Fatalf("verify corpus scan: %v", err)
	}
	if len(cases) == 0 {
		t.Fatal("verify corpus is empty")
	}
	return cases
}

// TestVerifyParityCorpus is the native-verify differential gate. For every case it
// runs the native direct rung over the injected oneline window and asserts:
//
//   - py_via == "direct"  → Go supported=true AND (shipped, sha, via, source) match.
//   - py_shipped == false → Go supported=true, shipped=false, source="none" (a clean
//     miss the generic convention resolves natively).
//   - py_via is a NON-direct rung (release-prefix/body/hyg-slug/sub-phase-parent/
//     file-path) → Go MUST abstain (supported=false), so the stop path delegates to
//     Python rather than report a native miss off an unported rung. A native
//     shipped/not-shipped answer here would be a turn-killing regression.
//
// The corpus is generated under the active (generic) convention; the Go side reads
// the generic convention from dos.toml the same way (readStampConvention), so the two
// see the same grammar.
func TestVerifyParityCorpus(t *testing.T) {
	cases := loadVerifyCorpus(t)
	conv := genericConvention{} // pure-generic, matching this repo's resolved [stamp]
	for _, c := range cases {
		c := c
		t.Run(c.Name, func(t *testing.T) {
			v := verifyDirect(c.Plan, c.Phase, c.Oneline, conv)

			pyNonDirectShip := c.PyShipped && c.PyVia != "direct"
			if pyNonDirectShip {
				// A ship resolved by a rung the native port does not own → MUST abstain.
				if v.supported {
					t.Fatalf("expected ABSTAIN on non-direct rung %q for %s %s, but native returned supported (shipped=%v via=%q)",
						c.PyVia, c.Plan, c.Phase, v.shipped, v.via)
				}
				return
			}

			// Otherwise (direct ship OR a clean miss) the native path must OWN it.
			if !v.supported {
				t.Fatalf("native unexpectedly abstained on %s %s (py: shipped=%v via=%q source=%q)",
					c.Plan, c.Phase, c.PyShipped, c.PyVia, c.PySource)
			}
			if v.shipped != c.PyShipped {
				t.Fatalf("SHIPPED drift on %q: py=%v go=%v", c.Name, c.PyShipped, v.shipped)
			}
			if v.via != c.PyVia {
				t.Fatalf("VIA drift on %q: py=%q go=%q", c.Name, c.PyVia, v.via)
			}
			if v.source != c.PySource {
				t.Fatalf("SOURCE drift on %q: py=%q go=%q", c.Name, c.PySource, v.source)
			}
			if v.shipped && v.sha != c.PySha {
				t.Fatalf("SHA drift on %q: py=%q go=%q", c.Name, c.PySha, v.sha)
			}
		})
	}
}

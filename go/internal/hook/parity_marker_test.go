package hook

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// markerCase is one budget walk from parity/corpus_marker.jsonl — a list of decisions,
// each carrying (prior_count, max_markers) and the EXACT verdict + dialect the Python
// marker decider produces. The Go test recomputes each via waitMarkerBudget +
// markerBlockReason and asserts byte-equality — the marker arm of the GHF differential
// gate. (The disk round-trip record→count is covered by the unit tests; this isolates
// the verdict + the emitted dialect bytes, the half that must match Python exactly.)
type markerCase struct {
	Name  string `json:"name"`
	Steps []struct {
		PriorCount     int    `json:"prior_count"`
		MaxMarkers     int    `json:"max_markers"`
		ExpectedAllow  bool   `json:"expected_allow"`
		ExpectedCarry  int    `json:"expected_carry"`
		ExpectedReason string `json:"expected_reason"`
		ExpectedStdout string `json:"expected_stdout"`
	} `json:"steps"`
}

func loadMarkerCorpus(t *testing.T) []markerCase {
	t.Helper()
	path := filepath.Join("parity", "corpus_marker.jsonl")
	f, err := os.Open(path)
	if err != nil {
		t.Fatalf("open %s: %v (run `python go/internal/hook/parity/gen_corpus_marker.py > %s`)", path, err, path)
	}
	defer f.Close()
	var cases []markerCase
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<20)
	for sc.Scan() {
		if len(sc.Bytes()) == 0 {
			continue
		}
		var c markerCase
		if err := json.Unmarshal(sc.Bytes(), &c); err != nil {
			t.Fatalf("marker corpus unmarshal: %v", err)
		}
		cases = append(cases, c)
	}
	if len(cases) == 0 {
		t.Fatal("marker corpus empty")
	}
	return cases
}

// TestParityMarkerCorpus recomputes each budget decision through the native verdict
// (waitMarkerBudget) + the block-dialect renderer (markerBlockReason + pyJSONDumps) and
// asserts the verdict bit, the carry count, the reason string, AND the emitted stdout
// are byte-identical to the Python decider's at EVERY prior_count — the marker arm of
// the GHF3 differential gate.
func TestParityMarkerCorpus(t *testing.T) {
	for _, c := range loadMarkerCorpus(t) {
		c := c
		t.Run(c.Name, func(t *testing.T) {
			for i, s := range c.Steps {
				v := waitMarkerBudget(s.PriorCount, s.MaxMarkers)
				if v.allow != s.ExpectedAllow {
					t.Fatalf("step %d (prior=%d max=%d): allow py=%v go=%v", i, s.PriorCount, s.MaxMarkers, s.ExpectedAllow, v.allow)
				}
				if v.markersEmitted != s.ExpectedCarry {
					t.Fatalf("step %d (prior=%d max=%d): carry py=%d go=%d", i, s.PriorCount, s.MaxMarkers, s.ExpectedCarry, v.markersEmitted)
				}
				if v.reason != s.ExpectedReason {
					t.Fatalf("step %d (prior=%d max=%d): REASON BYTE DRIFT\n  py: %q\n  go: %q", i, s.PriorCount, s.MaxMarkers, s.ExpectedReason, v.reason)
				}
				// The emitted stdout: the block dialect on allow, "" on refuse.
				got := ""
				if v.allow {
					payload := map[string]any{"decision": "block", "reason": markerBlockReason(v.reason)}
					got = pyJSONDumps(payload)
				}
				if got != s.ExpectedStdout {
					t.Fatalf("step %d (prior=%d max=%d): STDOUT BYTE DRIFT\n  py: %q\n  go: %q", i, s.PriorCount, s.MaxMarkers, s.ExpectedStdout, got)
				}
			}
		})
	}
}

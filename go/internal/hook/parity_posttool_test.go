package hook

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// posttoolCase is one stream-stateful sequence from parity/corpus_posttool.jsonl —
// a list of steps, each carrying the event + the EXACT dialect the Python posttool
// decider emits at that step. The Go test folds the events through the native
// classify+warn path and asserts byte-equality at every step.
type posttoolCase struct {
	Name  string `json:"name"`
	Steps []struct {
		Event          map[string]any `json:"event"`
		ExpectedStdout string         `json:"expected_stdout"`
	} `json:"steps"`
}

func loadPosttoolCorpus(t *testing.T) []posttoolCase {
	t.Helper()
	path := filepath.Join("parity", "corpus_posttool.jsonl")
	f, err := os.Open(path)
	if err != nil {
		t.Fatalf("open %s: %v (run `python go/internal/hook/parity/gen_corpus_posttool.py > %s`)", path, err, path)
	}
	defer f.Close()
	var cases []posttoolCase
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<20)
	for sc.Scan() {
		if len(sc.Bytes()) == 0 {
			continue
		}
		var c posttoolCase
		if err := json.Unmarshal(sc.Bytes(), &c); err != nil {
			t.Fatalf("posttool corpus unmarshal: %v", err)
		}
		cases = append(cases, c)
	}
	if len(cases) == 0 {
		t.Fatal("posttool corpus empty")
	}
	return cases
}

// TestParityPosttoolCorpus replays each stream sequence through the native
// classify+warn path (the pure half of DecidePosttool) and asserts the emitted
// dialect is byte-identical to the Python decider's at EVERY step — the
// stream-stateful arm of the GHF3 differential gate.
func TestParityPosttoolCorpus(t *testing.T) {
	for _, c := range loadPosttoolCorpus(t) {
		c := c
		t.Run(c.Name, func(t *testing.T) {
			var steps []streamStep
			for i, s := range c.Steps {
				step, ok := stepFromEvent(s.Event)
				if !ok {
					// No tool_name -> nothing recorded; the live hook emits nothing.
					if s.ExpectedStdout != "" {
						t.Fatalf("step %d: no tool_name but Python expected output %q", i, s.ExpectedStdout)
					}
					continue
				}
				steps = append(steps, step)
				v := classifyStream(steps)
				got := ""
				if p := postWarnPayload(v); p != nil {
					got = pyJSONDumps(p)
				}
				if got != s.ExpectedStdout {
					t.Fatalf("BYTE DRIFT %q step %d:\n  py: %q\n  go: %q", c.Name, i, s.ExpectedStdout, got)
				}
			}
		})
	}
}

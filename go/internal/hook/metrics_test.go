package hook

import (
	"strings"
	"testing"
)

// The in-process counter registry: count, add, snapshot ordering, dimension keys,
// and the latency bucket boundaries.

func TestCountAndAddAccumulate(t *testing.T) {
	resetMetricsForTest()
	Count(MInvocations, "pretool")
	Count(MInvocations, "pretool")
	Count(MInvocations, "stop")
	Add(MStopClaims, "", 3)
	Add(MStopClaims, "", 2)

	got := snapshotMap(t)
	if got["invocations|pretool"] != 2 {
		t.Fatalf("invocations|pretool = %d, want 2", got["invocations|pretool"])
	}
	if got["invocations|stop"] != 1 {
		t.Fatalf("invocations|stop = %d, want 1", got["invocations|stop"])
	}
	if got["stop_claims"] != 5 {
		t.Fatalf("stop_claims (summed) = %d, want 5", got["stop_claims"])
	}
}

func TestCountNBareKey(t *testing.T) {
	resetMetricsForTest()
	CountN(MMarkerRefuse)
	CountN(MMarkerRefuse)
	got := snapshotMap(t)
	if got["marker_refuse"] != 2 {
		t.Fatalf("marker_refuse = %d, want 2", got["marker_refuse"])
	}
	// A bare key must NOT carry a "|" dimension separator.
	for k := range got {
		if k == "marker_refuse|" {
			t.Fatalf("bare counter keyed with a trailing separator: %q", k)
		}
	}
}

func TestSnapshotIsSortedAndStable(t *testing.T) {
	resetMetricsForTest()
	Count(MPretoolDecision, "warn")
	Count(MPretoolDecision, "deny")
	Count(MPretoolDecision, "passthrough")
	snap := Snapshot()
	for i := 1; i < len(snap); i++ {
		if snap[i-1].Key > snap[i].Key {
			t.Fatalf("snapshot not sorted at %d: %q > %q", i, snap[i-1].Key, snap[i].Key)
		}
	}
}

func TestLatencyBucketBoundaries(t *testing.T) {
	cases := []struct {
		ns   int64
		want string
	}{
		{0, "1ms"},
		{1_000_000, "1ms"},         // exactly 1ms → 1ms (le)
		{1_000_001, "5ms"},         // just over 1ms → next bucket
		{10_000_000, "10ms"},       // exactly 10ms
		{10_000_001, "25ms"},       // just over
		{999_999_999, "1s"},        // under the last bound
		{1_000_000_000, "1s"},      // exactly 1s
		{2_000_000_000, "+Inf"},    // over the last bound
	}
	for _, c := range cases {
		if got := latencyBucketLabel(c.ns); got != c.want {
			t.Errorf("latencyBucketLabel(%d) = %q, want %q", c.ns, got, c.want)
		}
	}
}

func TestObserveLatencyRecordsSumCountBucket(t *testing.T) {
	resetMetricsForTest()
	observeLatency("pretool", 2_000_000)  // 2ms → 5ms bucket
	observeLatency("pretool", 8_000_000)  // 8ms → 10ms bucket
	got := snapshotMap(t)
	if got["latency_ns|pretool"] != 10_000_000 {
		t.Fatalf("latency_ns sum = %d, want 10_000_000", got["latency_ns|pretool"])
	}
	if got["latency_count|pretool"] != 2 {
		t.Fatalf("latency_count = %d, want 2", got["latency_count|pretool"])
	}
	if got["latency_bucket|pretool:5ms"] != 1 || got["latency_bucket|pretool:10ms"] != 1 {
		t.Fatalf("latency buckets wrong: %v", filterKeys(got, "latency_bucket|"))
	}
}

// A negative elapsed (clock skew) clamps to 0, never a negative counter.
func TestObserveLatencyClampsNegative(t *testing.T) {
	resetMetricsForTest()
	observeLatency("stop", -5)
	got := snapshotMap(t)
	if got["latency_ns|stop"] != 0 {
		t.Fatalf("negative latency not clamped: %d", got["latency_ns|stop"])
	}
}

// ---- helpers ----

func snapshotMap(t *testing.T) map[string]int64 {
	t.Helper()
	m := map[string]int64{}
	for _, s := range Snapshot() {
		m[s.Key] = s.Value
	}
	return m
}

func filterKeys(m map[string]int64, prefix string) map[string]int64 {
	out := map[string]int64{}
	for k, v := range m {
		if strings.HasPrefix(k, prefix) {
			out[k] = v
		}
	}
	return out
}

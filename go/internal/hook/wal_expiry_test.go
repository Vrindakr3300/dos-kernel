package hook

// Phantom-lease self-heal parity (FQ-532 / docs/281 Defect 1): the Go WAL reader
// `liveLeasesFromWALAt` must drop a crashed worker's un-RELEASEd ACQUIRE once it
// ages past its TTL+grace, instead of the PRE-admission hook enforcing a phantom
// lane on every tool call until an external SCAVENGE lands. Mirrors the Python
// `tests/test_lane_lease_expiry.py` semantics with the same clock injection seam.

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// writeAcquireWAL writes a one-record lane-journal holding a single live ACQUIRE
// with the given stamp/ttl, and returns its path (the disk LiveLeasesFromWAL reads).
func writeAcquireWAL(t *testing.T, lane, acquiredAt string, ttlMinutes float64) string {
	t.Helper()
	dir := t.TempDir()
	wal := filepath.Join(dir, "lane-journal.jsonl")
	rec := map[string]any{
		"op":      "ACQUIRE",
		"loop_ts": acquiredAt,
		"lane":    lane,
		"lease": map[string]any{
			"lane":        lane,
			"tree":        []string{lane + "/**"},
			"loop_ts":     acquiredAt,
			"acquired_at": acquiredAt,
			"ttl_minutes": ttlMinutes,
			"host_id":     "DESKTOP-TEST",
			"pid":         1,
		},
	}
	line, _ := json.Marshal(rec)
	if err := os.WriteFile(wal, append(line, '\n'), 0o644); err != nil {
		t.Fatalf("write wal: %v", err)
	}
	return wal
}

func stampMinutesAgo(now time.Time, mins float64) string {
	return now.Add(-time.Duration(mins * float64(time.Minute))).Format("2006-01-02T15:04:05Z")
}

func TestLeaseExpired_StaleByTTLIsExpired(t *testing.T) {
	now := time.Date(2026, 6, 9, 23, 0, 0, 0, time.UTC)
	// acquired 120 min ago, ttl 50 → 120 > 50+5 → expired
	lz := map[string]any{"acquired_at": stampMinutesAgo(now, 120), "ttl_minutes": 50.0}
	if !leaseExpired(lz, now) {
		t.Fatal("a lease 120m old with ttl 50 must be expired")
	}
}

func TestLeaseExpired_FreshIsKept(t *testing.T) {
	now := time.Date(2026, 6, 9, 23, 0, 0, 0, time.UTC)
	lz := map[string]any{"acquired_at": stampMinutesAgo(now, 1), "ttl_minutes": 50.0}
	if leaseExpired(lz, now) {
		t.Fatal("a 1m-old lease within ttl must NOT be expired")
	}
}

func TestLeaseExpired_NoStampIsKept(t *testing.T) {
	now := time.Date(2026, 6, 9, 23, 0, 0, 0, time.UTC)
	// No parseable stamp → cannot prove stale → kept (fail-safe).
	if leaseExpired(map[string]any{"ttl_minutes": 50.0}, now) {
		t.Fatal("a lease with no parseable stamp must be kept (cannot prove stale)")
	}
}

func TestLeaseExpired_DefaultTTLBackstop(t *testing.T) {
	now := time.Date(2026, 6, 9, 23, 0, 0, 0, time.UTC)
	// No ttl_minutes declared → default backstop (50). 120m old → expired.
	lz := map[string]any{"acquired_at": stampMinutesAgo(now, 120)}
	if !leaseExpired(lz, now) {
		t.Fatal("a lease with no ttl_minutes must age out by the default backstop")
	}
}

func TestLeaseExpired_HeartbeatWinsOverAcquiredAt(t *testing.T) {
	now := time.Date(2026, 6, 9, 23, 0, 0, 0, time.UTC)
	// Acquired 3h ago but heartbeating 1m ago → alive (heartbeat_at wins).
	lz := map[string]any{
		"acquired_at":  stampMinutesAgo(now, 180),
		"heartbeat_at": stampMinutesAgo(now, 1),
		"ttl_minutes":  50.0,
	}
	if leaseExpired(lz, now) {
		t.Fatal("a recently-heartbeating lease must be kept even with an old acquired_at")
	}
}

func TestLiveLeasesFromWAL_DropsPhantom(t *testing.T) {
	now := time.Date(2026, 6, 9, 23, 0, 0, 0, time.UTC)
	wal := writeAcquireWAL(t, "apply", stampMinutesAgo(now, 180), 50.0)
	live := liveLeasesFromWALAt(wal, now)
	for _, l := range live {
		if l.lane == "apply" {
			t.Fatal("the contention read must drop the phantom 'apply' orphan")
		}
	}
}

func TestLiveLeasesFromWAL_KeepsFreshLease(t *testing.T) {
	now := time.Date(2026, 6, 9, 23, 0, 0, 0, time.UTC)
	wal := writeAcquireWAL(t, "apply", stampMinutesAgo(now, 1), 50.0)
	live := liveLeasesFromWALAt(wal, now)
	found := false
	for _, l := range live {
		if l.lane == "apply" {
			found = true
		}
	}
	if !found {
		t.Fatal("a fresh live lease must still gate (be present in the contention read)")
	}
}

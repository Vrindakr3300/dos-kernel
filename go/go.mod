// The dos-kernel Go module — the native hook fast-path (docs/125 GHF).
//
// First Go in the dos repo. It exists for ONE reason: the per-tool-call hook hot
// path pays ~0.3–0.8 s of Python interpreter cold-start on EVERY tool call, and a
// static Go binary erases it (< 30 ms). The boundary is the one docs/100 fixed and
// docs/124 sharpened: Go is a PURE decider over the decision-bearing fields; the
// human-facing prose stays matchable-or-Python. See docs/125.
//
// Static, no-cgo, stdlib-only by design: the binary must cross-compile (the docs/122
// on-device payoff comes free later) and must not drag a dependency tree onto the
// hot path. If a dep is ever needed, it goes behind a build tag, never in the
// default hook decider.
module github.com/anthony-chaudhary/dos-kernel/go

go 1.25

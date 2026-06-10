package hook

import "strconv"

// pct0 renders a fraction as a whole-percent string the way Python's `f"{x:.0%}"`
// does: multiply by 100, round half-to-even to 0 decimals, append "%".
//
// docs/124 §1.1 is the load-bearing caveat: Python's `:.0%` and Go's
// strconv/fmt BOTH use IEEE-754 round-half-to-even for FIXED precision, so this
// agrees byte-for-byte with Python on the percentage. (The divergence docs/124
// warns about is SHORTEST-decimal — `%v`/`repr` — which we never use here.) This
// percentage only ever appears in the disjointness-collision `reason` prose, which
// is NOT part of the byte-gated decision projection; it is rendered faithfully so
// the advisory reason diff stays empty where it can, but a drift here can never
// move a verdict.
//
// strconv.FormatFloat(_, 'f', 0, 64) is Go's round-half-to-even fixed-precision
// formatter — the exact analogue of Python's format machinery for `:.0%`.
func pct0(x float64) string {
	return strconv.FormatFloat(x*100, 'f', 0, 64) + "%"
}

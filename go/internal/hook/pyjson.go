package hook

import (
	"fmt"
	"sort"
	"strconv"
	"strings"
)

// pyJSONDumps renders a value as bytes IDENTICAL to Python's
// `json.dumps(obj, sort_keys=True)` — the exact call cli.py makes
// (`print(json.dumps(host_dialect, sort_keys=True))`). The byte-exactness of this
// function IS the GHF parity contract for the emitted dialect, so it reproduces
// Python's defaults precisely:
//
//   - object keys SORTED ascending by Unicode code point (sort_keys=True), with
//     ": " between key and value and ", " between members (Python's default
//     non-compact separators).
//   - arrays with ", " between elements.
//   - strings with ensure_ascii=True: every non-ASCII rune escaped as \uXXXX
//     (surrogate pair for astral code points), and the JSON-mandatory escapes for
//     ", \, and the C0 controls. Python escapes ONLY these — notably it does NOT
//     escape "/" (Go's stdlib does), and it leaves printable ASCII verbatim.
//   - bool/nil/number rendered as Python would (true/false/null; ints without a
//     decimal point).
//
// This encoder is the single source of byte-truth; encoding/json is deliberately
// NOT used (it does not sort with Python's separators, does not ASCII-escape
// general non-ASCII, and HTML-escapes <,>,& by default).
func pyJSONDumps(v any) string {
	var b strings.Builder
	enc := encoder{ensureASCII: true}
	enc.encodeValue(&b, v)
	return b.String()
}

// pyJSONDumpsWAL renders a value as bytes IDENTICAL to the lane-journal's
// `json.dumps(e, sort_keys=True, default=str, ensure_ascii=False)` (lane_journal.append,
// line 294). The ONLY difference from pyJSONDumps is ensure_ascii=False: non-ASCII
// runes are emitted as raw UTF-8 (not \uXXXX). The WAL is the writer side; its line
// encoding must match Python's byte-for-byte so a journal Go writes and Python reads
// (or vice versa) round-trips. `default=str` only affects values json can't natively
// encode — the OP_ENFORCE entry carries only str/bool/None/int/nested-dict, all
// natively encodable, so there is no str() fallback to reproduce.
func pyJSONDumpsWAL(v any) string {
	var b strings.Builder
	enc := encoder{ensureASCII: false}
	enc.encodeValue(&b, v)
	return b.String()
}

// encoder carries the one knob that differs between the stdout dialect
// (ensure_ascii=True) and the WAL line (ensure_ascii=False).
type encoder struct{ ensureASCII bool }

func (e encoder) encodeValue(b *strings.Builder, v any) {
	switch x := v.(type) {
	case nil:
		b.WriteString("null")
	case bool:
		if x {
			b.WriteString("true")
		} else {
			b.WriteString("false")
		}
	case string:
		e.encodeString(b, x)
	case int:
		b.WriteString(strconv.Itoa(x))
	case int64:
		b.WriteString(strconv.FormatInt(x, 10))
	case float64:
		// Only used for whole counts in the dialect; render an integral float
		// without a trailing ".0" the way Python's json does for an int. The
		// dialect carries no fractional numbers, so this branch is defensive.
		if x == float64(int64(x)) {
			b.WriteString(strconv.FormatInt(int64(x), 10))
		} else {
			b.WriteString(strconv.FormatFloat(x, 'g', -1, 64))
		}
	case map[string]any:
		e.encodeObject(b, x)
	case []any:
		e.encodeArray(b, x)
	case []string:
		arr := make([]any, len(x))
		for i, s := range x {
			arr[i] = s
		}
		e.encodeArray(b, arr)
	default:
		// Defensive: fall back to a quoted Go-formatted string. The dialect maps
		// only ever carry the types above, so this is unreachable in practice.
		e.encodeString(b, fmt.Sprintf("%v", x))
	}
}

func (e encoder) encodeObject(b *strings.Builder, m map[string]any) {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys) // sort_keys=True — ascending by code point (ASCII keys here)
	b.WriteByte('{')
	for i, k := range keys {
		if i > 0 {
			b.WriteString(", ")
		}
		e.encodeString(b, k)
		b.WriteString(": ")
		e.encodeValue(b, m[k])
	}
	b.WriteByte('}')
}

func (e encoder) encodeArray(b *strings.Builder, a []any) {
	b.WriteByte('[')
	for i, v := range a {
		if i > 0 {
			b.WriteString(", ")
		}
		e.encodeValue(b, v)
	}
	b.WriteByte(']')
}

// encodeString reproduces Python's json string escaping. With ensureASCII it
// escapes every non-ASCII rune to \uXXXX (the stdout dialect, ensure_ascii=True);
// without it, non-ASCII is emitted as raw UTF-8 (the WAL line, ensure_ascii=False).
// The JSON-mandatory escapes (", \, C0 controls) apply in BOTH modes.
func (e encoder) encodeString(b *strings.Builder, s string) {
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString("\\\"")
		case '\\':
			b.WriteString("\\\\")
		case '\n':
			b.WriteString("\\n")
		case '\r':
			b.WriteString("\\r")
		case '\t':
			b.WriteString("\\t")
		case '\b':
			b.WriteString("\\b")
		case '\f':
			b.WriteString("\\f")
		default:
			switch {
			case r < 0x20:
				// Other C0 control characters -> \u00XX (both modes — JSON requires it).
				fmt.Fprintf(b, "\\u%04x", r)
			case r < 0x7f:
				b.WriteRune(r) // printable ASCII verbatim
			case r == 0x7f:
				b.WriteRune(r) // DEL left verbatim by Python's json
			case !e.ensureASCII:
				// ensure_ascii=False: non-ASCII emitted as raw UTF-8.
				b.WriteRune(r)
			case r <= 0xffff:
				fmt.Fprintf(b, "\\u%04x", r)
			default:
				// Astral plane: emit a UTF-16 surrogate pair, like Python.
				r2 := r - 0x10000
				hi := 0xd800 + (r2 >> 10)
				lo := 0xdc00 + (r2 & 0x3ff)
				fmt.Fprintf(b, "\\u%04x\\u%04x", hi, lo)
			}
		}
	}
	b.WriteByte('"')
}

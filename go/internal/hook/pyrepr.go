package hook

import "strings"

// pyRepr renders a string the way Python's `repr()` (and thus an f-string `!r`)
// does — the admission reasons interpolate the lane name with `{request.lane!r}`,
// so to byte-match the reason prose the Go side must reproduce Python's quoting.
//
// Python's str repr rules (the subset reachable from a lane name, which is a tool
// name like "Edit"/"Bash"/"mcp__x__y" — printable ASCII, no control chars):
//   - default quote is the single quote '.
//   - if the string contains a ' but no ", switch to double quotes " (so the '
//     need not be escaped).
//   - otherwise use ' and backslash-escape any embedded '.
//   - a backslash is always escaped to \\.
//
// Lane names are tool names and never contain control characters, quotes, or
// backslashes in practice, so the common path is just `'name'`. The quote-switch
// and escaping are implemented for completeness so a pathological tool name still
// matches Python byte-for-byte. (The reason prose is advisory, not part of the
// gated decision projection, but matching it keeps the GHF3 reason-diff clean.)
func pyRepr(s string) string {
	hasSingle := strings.Contains(s, "'")
	hasDouble := strings.Contains(s, "\"")
	quote := byte('\'')
	if hasSingle && !hasDouble {
		quote = '"'
	}
	var b strings.Builder
	b.WriteByte(quote)
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case c == '\\':
			b.WriteString("\\\\")
		case c == quote:
			b.WriteByte('\\')
			b.WriteByte(c)
		case c == '\n':
			b.WriteString("\\n")
		case c == '\r':
			b.WriteString("\\r")
		case c == '\t':
			b.WriteString("\\t")
		default:
			b.WriteByte(c)
		}
	}
	b.WriteByte(quote)
	return b.String()
}

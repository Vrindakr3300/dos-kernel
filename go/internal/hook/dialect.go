package hook

// denyPayload is the CC PreToolUse DENY dialect — port of
// `dos.pretool_sensor.deny_payload`. permissionDecision: deny is the one envelope
// real Claude Code honors to block a tool BEFORE it runs. Field names are
// case-sensitive and exact. NEVER emits updatedInput (a byte-author violation).
func denyPayload(reason, additionalContext string) map[string]any {
	inner := map[string]any{
		"hookEventName":            "PreToolUse",
		"permissionDecision":       "deny",
		"permissionDecisionReason": reason,
	}
	if additionalContext != "" {
		inner["additionalContext"] = additionalContext
	}
	return map[string]any{"hookSpecificOutput": inner}
}

// warnPayload is the CC PreToolUse WARN dialect — additionalContext ONLY, no
// permissionDecision. Port of `dos.pretool_sensor.warn_payload`. A WARN does not
// deny: CC's normal permission flow proceeds; the agent only gets an added fact.
func warnPayload(text string) map[string]any {
	return map[string]any{
		"hookSpecificOutput": map[string]any{
			"hookEventName":     "PreToolUse",
			"additionalContext": text,
		},
	}
}

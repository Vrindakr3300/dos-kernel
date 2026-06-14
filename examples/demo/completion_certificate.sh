#!/usr/bin/env bash
# The completion certificate, runnable end to end in a throwaway directory.
#
# Every coding agent today closes the loop on its OWN claim: it says "done," the
# turn ends. This demo turns that claim into a CERTIFICATE — {claim, witness,
# source, verdict} — where the verdict comes from git (a witness the agent did
# not author), not the agent's word. The industry moved off tokens-burned to
# "verified outcomes"; this is the outcome, made into an artifact you can read.
#
#   bash examples/demo/completion_certificate.sh
#
# It builds on the SAME canonical AUTH story as verify_demo.sh. An agent claims it
# shipped two phases:
#   - the login endpoint (AUTH1) — a real commit landed it
#   - the password reset (AUTH2) — nothing ever landed
# The certificate tells them apart from the artifacts, not the claim.
#
# Requires: `dos` on PATH (pip install -e .) and git. No agents, no fleet.
set -euo pipefail

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"

git init -q
git config user.email demo@example.com
git config user.name  "Demo"
git config commit.gpgsign false
echo 'def login(): ...' > login.py
git add -A
git commit -q -m "AUTH1: ship the login endpoint"

echo "# The agent's turn-ending claim:"
echo '#   "Done! Shipped the login endpoint (AUTH1) and the password reset (AUTH2)."'
echo "#"
echo "# A completion certificate per claimed phase — the verdict is git's, not the agent's:"
echo

# Render one certificate line per claimed (plan, phase). The witness/source/verdict
# all come from `dos verify --json`; the claim is what the agent said it shipped.
certify() {
  plan="$1"; phase="$2"; claim="$3"
  json="$(dos verify --workspace . "$plan" "$phase" --json 2>/dev/null || true)"
  # parse the small, stable {plan, phase, shipped, source} object with stdlib python
  read -r shipped source <<EOF
$(printf '%s' "$json" | python -c 'import sys,json; d=json.load(sys.stdin); print(str(d.get("shipped")).lower(), d.get("source","none"))')
EOF
  if [ "$shipped" = "true" ]; then verdict="SHIPPED   ✓"; else verdict="NOT_SHIPPED ✗"; fi
  echo   "  ── completion certificate ──────────────────────────────"
  printf '  claim   : %s\n' "$claim"
  printf '  witness : git ancestry over the ship-commit grammar\n'
  printf '  source  : %s\n' "$source"
  printf '  verdict : %s  (%s %s)\n' "$verdict" "$plan" "$phase"
  echo
}

certify AUTH AUTH1 "shipped the login endpoint (AUTH1)"
certify AUTH AUTH2 "shipped the password reset (AUTH2)"

echo "# source=none on AUTH2 means DOS checked everywhere it trusts and found nothing"
echo "# behind the claim. The agent said 'done'; the certificate says otherwise — and"
echo "# it says WHY, with a source field a self-report can never carry."

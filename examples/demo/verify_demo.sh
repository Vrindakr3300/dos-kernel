#!/usr/bin/env bash
# The DOS money-moment, runnable end to end in a throwaway directory.
#
# An agent *claims* a unit of work is done. DOS doesn't believe it — it asks git.
# Every line in the examples/demo/verify_visual.html walkthrough is verbatim output
# of THIS script; re-run it to regenerate the cast. No agents, no fleet, no plan
# files — just the truth syscall, working, against a plain git repo.
#
#   bash examples/demo/verify_demo.sh
#
# Requires: `dos` on PATH (pip install -e .) and git.
set -euo pipefail

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"

echo "\$ dos init ."
dos init . | sed 's/^/  /'
echo

echo "\$ git init -q && git commit -m 'AUTH1: ship the login endpoint'"
git init -q
git config user.email demo@example.com
git config user.name  "Demo"
git config commit.gpgsign false
echo 'def login(): pass' > login.py
git add -A
git commit -q -m "AUTH1: ship the login endpoint"
echo "  [committed $(git rev-parse --short HEAD)]"
echo

echo "# An agent says AUTH1 shipped. Was it true? Ask git, not the agent:"
echo "\$ dos verify AUTH AUTH1"
dos verify --workspace . AUTH AUTH1 || true
echo "  exit=$?  (0 = the verdict is SHIPPED)"
echo

echo "# Now an agent claims AUTH2 is done too — but nothing ever landed:"
echo "\$ dos verify AUTH AUTH2"
set +e
dos verify --workspace . AUTH AUTH2
code=$?
set -e
echo "  exit=$code  (1 = NOT_SHIPPED — the claim is contradicted by the artifacts)"

# The completion certificate, runnable end to end in a throwaway directory (PowerShell).
#
# Every coding agent today closes the loop on its OWN claim: it says "done," the
# turn ends. This demo turns that claim into a CERTIFICATE — {claim, witness,
# source, verdict} — where the verdict comes from git (a witness the agent did
# not author), not the agent's word. The industry moved off tokens-burned to
# "verified outcomes"; this is the outcome, made into an artifact you can read.
#
#   pwsh examples/demo/completion_certificate.ps1
#
# It builds on the SAME canonical AUTH story as verify_demo.ps1. An agent claims it
# shipped two phases:
#   - the login endpoint (AUTH1) -- a real commit landed it
#   - the password reset (AUTH2) -- nothing ever landed
# The certificate tells them apart from the artifacts, not the claim.
#
# Requires: `dos` on PATH (pip install -e .) and git. No agents, no fleet.
$ErrorActionPreference = 'Stop'
$work = Join-Path ([System.IO.Path]::GetTempPath()) ("dos-cert-" + [System.IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Path $work -Force | Out-Null
try {
    Set-Location $work

    git init -q
    git config user.email demo@example.com
    git config user.name  "Demo"
    git config commit.gpgsign false
    git config core.autocrlf false
    Set-Content -Path login.py -Value 'def login(): ...' -Encoding ascii
    git add -A
    git commit -q -m "AUTH1: ship the login endpoint"

    Write-Output "# The agent's turn-ending claim:"
    Write-Output '#   "Done! Shipped the login endpoint (AUTH1) and the password reset (AUTH2)."'
    Write-Output '#'
    Write-Output '# A completion certificate per claimed phase — the verdict is git''s, not the agent''s:'
    Write-Output ''

    function Certify($plan, $phase, $claim) {
        $json = (dos verify --workspace . $plan $phase --json 2>$null) -join ''
        $d = $json | ConvertFrom-Json
        $shipped = [bool]$d.shipped
        $source  = if ($d.source) { $d.source } else { 'none' }
        $verdict = if ($shipped) { 'SHIPPED   (ok)' } else { 'NOT_SHIPPED (x)' }
        Write-Output '  -- completion certificate ------------------------------'
        Write-Output "  claim   : $claim"
        Write-Output '  witness : git ancestry over the ship-commit grammar'
        Write-Output "  source  : $source"
        Write-Output "  verdict : $verdict  ($plan $phase)"
        Write-Output ''
    }

    Certify 'AUTH' 'AUTH1' 'shipped the login endpoint (AUTH1)'
    Certify 'AUTH' 'AUTH2' 'shipped the password reset (AUTH2)'

    Write-Output '# source=none on AUTH2 means DOS checked everywhere it trusts and found nothing'
    Write-Output '# behind the claim. The agent said "done"; the certificate says otherwise -- and'
    Write-Output '# it says WHY, with a source field a self-report can never carry.'
}
finally {
    Set-Location ([System.IO.Path]::GetTempPath())
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}

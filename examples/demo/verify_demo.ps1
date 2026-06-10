# The DOS money-moment, runnable end to end in a throwaway directory (PowerShell).
#
# An agent *claims* a unit of work is done. DOS doesn't believe it — it asks git.
# Every line in the examples/demo/verify_visual.html walkthrough is verbatim output
# of this flow; re-run it to regenerate the cast. No agents, no fleet, no plan
# files — just the truth syscall, working, against a plain git repo.
#
#   pwsh examples/demo/verify_demo.ps1
#
# Requires: `dos` on PATH (pip install -e .) and git.
$ErrorActionPreference = 'Stop'
$work = Join-Path ([System.IO.Path]::GetTempPath()) ("dos-demo-" + [System.IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Path $work -Force | Out-Null
try {
    Set-Location $work

    Write-Output '$ dos init .'
    dos init . | ForEach-Object { "  $_" }
    Write-Output ''

    Write-Output "`$ git init -q && git commit -m 'AUTH1: ship the login endpoint'"
    git init -q
    git config user.email demo@example.com
    git config user.name  "Demo"
    git config commit.gpgsign false
    git config core.autocrlf false
    Set-Content -Path login.py -Value 'def login(): pass' -Encoding ascii
    git add -A
    git commit -q -m "AUTH1: ship the login endpoint"
    Write-Output "  [committed $(git rev-parse --short HEAD)]"
    Write-Output ''

    Write-Output '# An agent says AUTH1 shipped. Was it true? Ask git, not the agent:'
    Write-Output '$ dos verify AUTH AUTH1'
    dos verify --workspace . AUTH AUTH1
    Write-Output "  exit=$LASTEXITCODE  (0 = the verdict is SHIPPED)"
    Write-Output ''

    Write-Output '# Now an agent claims AUTH2 is done too — but nothing ever landed:'
    Write-Output '$ dos verify AUTH AUTH2'
    dos verify --workspace . AUTH AUTH2
    Write-Output "  exit=$LASTEXITCODE  (1 = NOT_SHIPPED — the claim is contradicted by the artifacts)"
}
finally {
    Set-Location ([System.IO.Path]::GetTempPath())
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}

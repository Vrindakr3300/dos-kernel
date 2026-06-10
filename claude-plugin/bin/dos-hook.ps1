# dos-hook.ps1 — the PowerShell launcher for the native DOS hook fast-path
# (docs/125 GHF4). The Windows sibling of the POSIX `dos-hook` launcher.
#
# NOT wired by the bundled hooks.json. The plugin's hooks declare `shell: bash`,
# which Claude Code runs through Git Bash even on Windows — so the POSIX `dos-hook`
# launcher (which recognises the MINGW*/MSYS*/CYGWIN* `uname` and dispatches to
# `dos-hook-windows-<arch>.exe`) already serves every platform. This .ps1 is a
# MANUAL-INTEGRATION helper: use it if you wire a `shell: powershell` hook yourself
# (e.g. on a Windows box with no Git Bash). It is on the `_MANUAL_LAUNCHERS`
# allowlist in scripts/build_plugin.py so the reachability check tolerates it being
# unreferenced; everything else under bin/ must be reached by some hooks.json command.
#
# It picks the bundled windows-<arch> binary and execs it; if absent (or the build
# was skipped), it falls through to the Python verb — the docs/100 fallback, so no
# machine is blocked.
#
# The first arg is the hook verb (pretool|posttool|stop); the rest pass through.
# The binary owns the per-verb fallback (exit 3 = DELEGATE → the hooks.json
# `|| python ...`), so this launcher only locates a binary for this arch.

$ErrorActionPreference = 'SilentlyContinue'
$selfDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# PROCESSOR_ARCHITECTURE is the EMULATED arch in a 32-bit/WOW process; on Windows-on-ARM
# a native amd64 PowerShell reports AMD64. We ship BOTH windows/amd64 and windows/arm64,
# so map each to its own binary; PROCESSOR_ARCHITEW6432 (the host arch when emulated)
# disambiguates an ARM host running an x86 shell. Unknown → amd64 (the common case;
# falls through to Python if that binary is somehow absent).
$arch = $env:PROCESSOR_ARCHITECTURE
if ($env:PROCESSOR_ARCHITEW6432) { $arch = $env:PROCESSOR_ARCHITEW6432 }
switch ($arch) {
  'AMD64' { $goarch = 'amd64' }
  'ARM64' { $goarch = 'arm64' }
  default { $goarch = 'amd64' }
}
$bin = Join-Path $selfDir "dos-hook-windows-$goarch.exe"

if (Test-Path $bin) {
  # The hook event arrives on stdin; the binary reads it. `&` runs the binary;
  # its exit code becomes ours so the hooks.json `||` sees a DELEGATE (exit 3).
  & $bin @args
  exit $LASTEXITCODE
}

# No native binary — fall back to the Python verb. The first arg is the verb.
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if ($py) {
  $verb = $args[0]
  $rest = @()
  if ($args.Count -gt 1) { $rest = $args[1..($args.Count - 1)] }
  & $py.Source -m dos.cli hook $verb @rest
  exit $LASTEXITCODE
}
# Neither a native binary nor Python — emit nothing, exit 0 (the hook fail-safe).
exit 0

<#
  Build the landmark models with your installed Blender (headless), e.g.
    powershell -File tools\landmarks\blender.ps1                  # all landmarks
    powershell -File tools\landmarks\blender.ps1 clock-tower      # just one

  Runs tools\landmarks\prepare.mjs (footprints + roof skeletons), then build.py inside Blender.
  Blender from the Microsoft Store only runs through its "blender-launcher" alias, which returns
  at once, so this waits for build.py's log to say it has finished.
#>
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Only)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$log = Join-Path $root "work\landmarks\build.log"

node (Join-Path $PSScriptRoot "prepare.mjs")
if ($LASTEXITCODE) { exit 1 }

$blender = (Get-Command blender -ErrorAction SilentlyContinue).Source
if (-not $blender) { $blender = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\blender-launcher.exe" }
Remove-Item $log -ErrorAction SilentlyContinue
$blenderArgs = @("--background", "--factory-startup", "--python", "`"$(Join-Path $PSScriptRoot 'build.py')`"", "--") + $Only
Start-Process -FilePath $blender -ArgumentList $blenderArgs -WindowStyle Hidden | Out-Null

$deadline = (Get-Date).AddMinutes(10)
while ((Get-Date) -lt $deadline) {
  if ((Test-Path $log) -and (Select-String -Path $log -Pattern "^(done|failed)$" -Quiet)) { break }
  Start-Sleep -Seconds 2
}
if (Test-Path $log) { Get-Content $log } else { Write-Host "Blender didn't start (no log)." -ForegroundColor Yellow; exit 1 }
if (Select-String -Path $log -Pattern "^failed$" -Quiet) { exit 1 }

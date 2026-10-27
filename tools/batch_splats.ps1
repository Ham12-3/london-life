<#
  Turn every downloaded clip in tools/shotlist.json into a fitted splat.

  Run the two stages side by side (COLMAP uses the CPU, Brush the GPU):
    .\tools\batch_splats.ps1 -Stage poses
    .\tools\batch_splats.ps1 -Stage train

  poses: solves camera poses for each job          -> work\<id>\poses.ok / poses.failed
  train: waits for each job's poses, trains it, fits it to the map, adds it to the manifest.
  Jobs that already have a fitted splat are skipped, so either stage can be re-run.
#>
param(
  [Parameter(Mandatory = $true)][ValidateSet("poses", "train")][string]$Stage,
  [int]$Fps = 4,
  [int]$Steps = 3000
)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
$log = Join-Path $root "work\batch-$Stage.log"

# Re-scan after each pass so clips downloaded while the batch runs are picked up too.
do {
$jobs = & python -I tools\batch_jobs.py | Where-Object { $_ } | ForEach-Object {
  $f = $_ -split "`t"
  [pscustomobject]@{ Id = $f[0]; Place = $f[1]; Videos = $f[2] -split "," }
}
$worked = 0
$pending = 0
Write-Host "$Stage stage: $($jobs.Count) jobs"

foreach ($job in $jobs) {
  $work = Join-Path $root "work\$($job.Id)"
  $stamp = Get-Date -Format "HH:mm:ss"
  if ($Stage -eq "poses") {
    if ((Test-Path "$work\poses.ok") -or (Test-Path "$work\poses.failed")) { continue }
    $worked++
    Add-Content $log "$stamp poses  $($job.Id)"
    & "$root\tools\video_to_splat.ps1" -Video $job.Videos -Name $job.Id -Fps $Fps -SkipTraining *> "$root\work\$($job.Id).poses.txt"
    if (-not (Test-Path "$work\poses.ok")) {
      New-Item -ItemType Directory -Force $work | Out-Null
      Set-Content "$work\poses.failed" "COLMAP could not register this clip"
      Add-Content $log "$(Get-Date -Format HH:mm:ss) FAILED poses $($job.Id)"
    } else {
      Add-Content $log "$(Get-Date -Format HH:mm:ss) ok     $($job.Id): $(Get-Content "$work\poses.ok")"
    }
  } else {
    # Train whatever has poses ready; places still waiting are picked up on a later pass.
    if (-not (Test-Path "$work\poses.ok")) { if (-not (Test-Path "$work\poses.failed")) { $pending++ }; continue }
    if (Test-Path "$work\train.failed") { continue }
    $worked++
    Add-Content $log "$stamp train  $($job.Id)"
    & "$root\tools\video_to_splat.ps1" -Video $job.Videos -Name $job.Id -Steps $Steps -SkipPoses *> "$root\work\$($job.Id).train.txt"
    if (-not (Test-Path "$root\public\assets\splats\$($job.Id).ply")) {
      Set-Content "$work\train.failed" "Brush did not export"
      Add-Content $log "$(Get-Date -Format HH:mm:ss) FAILED train $($job.Id)"; continue
    }
    $fit = & python -I tools\align_splat.py $job.Id $job.Place 2>&1 | Out-String
    if ($LASTEXITCODE) {
      Set-Content "$work\train.failed" $fit
      Add-Content $log "$(Get-Date -Format HH:mm:ss) FAILED fit $($job.Id): $fit"; continue
    }
    & python -I tools\batch_jobs.py --done $job.Id
    Add-Content $log "$(Get-Date -Format HH:mm:ss) done   $($job.Id): $(($fit -split "`n" | Select-String 'fit score|kept') -join ' | ')"
  }
}
if ($worked -eq 0 -and $pending -gt 0) { Start-Sleep -Seconds 30 }
} while ($worked -gt 0 -or $pending -gt 0)
Add-Content $log "$(Get-Date -Format HH:mm:ss) $Stage stage finished"

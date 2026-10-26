<#
  Turn a Google Flow clip into a Gaussian splat for the simulation.

    .\tools\video_to_splat.ps1 -Video assets\videos\09-casson-pavilion.mp4 -Name casson-pavilion

  Chained clips (each continuing the previous one's orbit from its last frame) solve as one:
    .\tools\video_to_splat.ps1 -Video a.mp4,b.mp4,c.mp4 -Name casson-pavilion
  Add -SkipPoses to retrain from an existing COLMAP solve.

  1. ffmpeg pulls frames out of the clip                 -> work\<Name>\images
  2. COLMAP solves camera poses (CPU)                    -> work\<Name>\sparse\0
  3. Brush trains the splat (any GPU, incl. Intel Iris)  -> public\assets\splats\<Name>.ply
  4. Add an entry to public\assets\manifest.json (see README) and reload the simulation.

  COLMAP and Brush are looked up on PATH first, then in .tools\ (see README for setup).
#>
param(
  [Parameter(Mandatory = $true)][string[]]$Video,
  [Parameter(Mandatory = $true)][string]$Name,
  [int]$Fps = 8,
  [int]$Steps = 7000,
  [int]$CheckpointEvery = 500,
  [switch]$SkipTraining,
  [switch]$SkipPoses
)
# COLMAP logs to stderr; under "Stop", Windows PowerShell 5.1 would treat that as fatal. Exit codes are checked instead.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$work = Join-Path $root "work\$Name"
$images = Join-Path $work "images"

function Find-Tool($command, $fallback) {
  $onPath = Get-Command $command -ErrorAction SilentlyContinue
  if ($onPath) { return $onPath.Source }
  $local = Join-Path $root $fallback
  if (Test-Path $local) { return $local }
  return $null
}
$colmap = Find-Tool "colmap" ".tools\colmap\COLMAP.bat"
$brush = Find-Tool "brush_app" ".tools\brush\brush_app.exe"

if (-not $SkipPoses) {
  if (Test-Path $work) { Remove-Item -Recurse -Force $work }
  New-Item -ItemType Directory -Force $images | Out-Null

  # Chained clips become one frame sequence; each continuation's first frame duplicates the
  # previous clip's last frame, so it's skipped.
  $count = 0
  foreach ($clip in $Video) {
    $tmp = Join-Path $work "clip-frames"
    New-Item -ItemType Directory -Force $tmp | Out-Null
    Write-Host "Extracting frames from $clip at $Fps fps..."
    ffmpeg -v error -y -i $clip -vf "fps=$Fps" -q:v 2 (Join-Path $tmp "%04d.jpg")
    $frames = Get-ChildItem $tmp -Filter *.jpg | Sort-Object Name
    if ($count -gt 0) { $frames = $frames | Select-Object -Skip 1 }
    foreach ($f in $frames) { $count++; Move-Item $f.FullName (Join-Path $images ("{0:D4}.jpg" -f $count)) }
    Remove-Item -Recurse -Force $tmp
  }
  Write-Host "  $count frames in $images"

  if (-not $colmap) {
    Write-Host "COLMAP not found on PATH or in .tools\colmap. See README to install it." -ForegroundColor Yellow
    exit 1
  }

  $db = Join-Path $work "database.db"
  $sparse = Join-Path $work "sparse"
  New-Item -ItemType Directory -Force $sparse | Out-Null
  Write-Host "Solving camera poses with COLMAP..."
  # AI video has no real lens distortion, so one shared pinhole camera is the right model.
  & $colmap feature_extractor --database_path $db --image_path $images `
    --ImageReader.single_camera 1 --ImageReader.camera_model PINHOLE --FeatureExtraction.use_gpu 0 2>&1 | Out-Null
  if ($LASTEXITCODE) { Write-Host "COLMAP feature extraction failed." -ForegroundColor Yellow; exit 1 }
  & $colmap sequential_matcher --database_path $db --FeatureMatching.use_gpu 0 --SequentialMatching.overlap 15 2>&1 | Out-Null
  if ($LASTEXITCODE) { Write-Host "COLMAP matching failed." -ForegroundColor Yellow; exit 1 }
  & $colmap mapper --database_path $db --image_path $images --output_path $sparse 2>&1 | Out-Null
  # COLMAP sometimes splits a clip into several models; keep the one with the most frames as model 0.
  $models = Get-ChildItem $sparse -Directory | Sort-Object { (Get-Item (Join-Path $_.FullName "images.bin")).Length } -Descending
  if ($models.Count -gt 1 -and $models[0].Name -ne "0") {
    Rename-Item (Join-Path $sparse "0") "0-small"
    Rename-Item $models[0].FullName "0"
  }
  $model = Join-Path $sparse "0"
  if (-not (Test-Path $model)) {
    Write-Host "COLMAP couldn't register the frames. The clip probably has too little camera movement;" -ForegroundColor Yellow
    Write-Host "regenerate it with a wider orbit." -ForegroundColor Yellow
    exit 1
  }
  & $colmap model_converter --input_path $model --output_path $model --output_type TXT 2>&1 | Out-Null
  $registered = (Get-Content (Join-Path $model "images.txt") | Where-Object { $_ -and -not $_.StartsWith("#") }).Count / 2
  $points = (Get-Content (Join-Path $model "points3D.txt") | Where-Object { $_ -and -not $_.StartsWith("#") }).Count
  Write-Host "  registered $registered of $count frames, $points sparse points"
  Set-Content (Join-Path $work "poses.ok") "$registered/$count frames, $points points"
}

if ($SkipTraining) { exit 0 }
if (-not $brush) {
  Write-Host "Brush not found on PATH or in .tools\brush. See README to install it." -ForegroundColor Yellow
  exit 1
}
$out = Join-Path $root "public\assets\splats"
New-Item -ItemType Directory -Force $out | Out-Null
if (-not $env:WGPU_BACKEND) { $env:WGPU_BACKEND = "vulkan" }
# Brush 0.3 crashes at random points mid-training on Intel Iris Xe (a GPU timing panic while splats
# are being refined). Train in checkpointed runs: after a crash, resume from the last checkpoint,
# which Brush loads as init.ply.
$ckpt = Join-Path $work "checkpoints"
Remove-Item -Recurse -Force $ckpt, (Join-Path $work "init.ply") -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $ckpt | Out-Null
$iter = 0
for ($attempt = 1; $iter -lt $Steps -and $attempt -le 30; $attempt++) {
  Write-Host "Training splat with Brush: steps $iter -> $Steps ($($env:WGPU_BACKEND), run $attempt)..."
  $runArgs = @($work, "--total-steps", $Steps, "--start-iter", $iter, "--export-every", $CheckpointEvery,
    "--export-path", $ckpt, "--export-name", "ckpt_{iter}.ply")
  $p = Start-Process -FilePath $brush -ArgumentList $runArgs -NoNewWindow -PassThru `
    -RedirectStandardOutput (Join-Path $work "brush-out.txt") -RedirectStandardError (Join-Path $work "brush-err.txt")
  $p | Wait-Process
  $latest = Get-ChildItem $ckpt -Filter "ckpt_*.ply" | Sort-Object { [int]($_.BaseName -replace "ckpt_", "") } | Select-Object -Last 1
  $reached = if ($latest) { [int]($latest.BaseName -replace "ckpt_", "") } else { 0 }
  if ($reached -le $iter -and $p.ExitCode -ne 0) { Write-Host "  crashed before the next checkpoint; retrying" }
  elseif ($p.ExitCode -ne 0) { Write-Host "  crashed after step $reached; resuming" }
  $iter = $reached
  if ($latest) { Copy-Item $latest.FullName (Join-Path $work "init.ply") -Force }
}
if ($iter -lt $Steps) {
  Write-Host "Brush kept crashing; stopped at step $iter." -ForegroundColor Yellow
  exit 1
}
Copy-Item (Join-Path $ckpt "ckpt_$Steps.ply") (Join-Path $out "$Name.ply") -Force
Write-Host ""
Write-Host "Splat ready: public\assets\splats\$Name.ply"
Write-Host "Add it to public\assets\manifest.json and reload the simulation."

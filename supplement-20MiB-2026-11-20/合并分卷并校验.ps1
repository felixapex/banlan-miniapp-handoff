param(
  [string]$PartsDirectory = $PSScriptRoot,
  [string]$OutputDirectory = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'
$manifestPath = Join-Path $PartsDirectory '分卷SHA256校验清单.json'
if (-not (Test-Path -LiteralPath $manifestPath)) {
  throw "找不到分卷清单：$manifestPath"
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$outputPath = Join-Path $OutputDirectory $manifest.archiveFile
if (Test-Path -LiteralPath $outputPath) {
  throw "目标文件已存在，为防止覆盖已停止：$outputPath"
}

foreach ($part in $manifest.parts) {
  $partPath = Join-Path $PartsDirectory $part.file
  if (-not (Test-Path -LiteralPath $partPath)) {
    throw "缺少分卷：$($part.file)"
  }
  $actual = (Get-FileHash -LiteralPath $partPath -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -ne $part.sha256.ToLowerInvariant()) {
    throw "分卷 SHA256 不一致：$($part.file)"
  }
}

$destination = [IO.File]::Open($outputPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try {
  foreach ($part in $manifest.parts) {
    $partPath = Join-Path $PartsDirectory $part.file
    $source = [IO.File]::OpenRead($partPath)
    try {
      $source.CopyTo($destination)
    }
    finally {
      $source.Dispose()
    }
  }
}
finally {
  $destination.Dispose()
}

$output = Get-Item -LiteralPath $outputPath
if ($output.Length -ne [int64]$manifest.archiveBytes) {
  throw "合并后大小不一致：期望 $($manifest.archiveBytes)，实际 $($output.Length)"
}
$archiveHash = (Get-FileHash -LiteralPath $outputPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($archiveHash -ne $manifest.archiveSha256.ToLowerInvariant()) {
  throw "整包 SHA256 不一致：期望 $($manifest.archiveSha256)，实际 $archiveHash"
}

Write-Host "合并与校验通过：$outputPath"
Write-Host "SHA256：$archiveHash"

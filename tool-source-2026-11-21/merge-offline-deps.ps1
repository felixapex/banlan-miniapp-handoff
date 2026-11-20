$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($PSScriptRoot)
$parts = Get-ChildItem -LiteralPath $root -File -Filter 'miniapp-execution-offline-deps-2026-11-21.zip.*' | Sort-Object Name
if ($parts.Count -ne 4) { throw "Expected 4 parts, found $($parts.Count)" }

$output = Join-Path $root '微信小程序执行工具_离线依赖_2026-11-21.zip'
if (Test-Path -LiteralPath $output) { throw "Output already exists: $output" }

$stream = [IO.File]::Create($output)
try {
    foreach ($part in $parts) {
        $input = [IO.File]::OpenRead($part.FullName)
        try { $input.CopyTo($stream) } finally { $input.Dispose() }
    }
} finally {
    $stream.Dispose()
}

$expected = '86f33bc99b18207729c93bdd8f505e90991eea577f1c9e40ea0bea92f9f0a963'
$actual = (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw "SHA256 mismatch: $actual" }
Write-Host "OK: $output"
Write-Host "SHA256: $actual"

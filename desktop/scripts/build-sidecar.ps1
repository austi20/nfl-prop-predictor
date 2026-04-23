$ErrorActionPreference = "Stop"

$desktopDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$repoRoot = Resolve-Path (Join-Path $desktopDir "..")
$binaryDir = Join-Path $desktopDir "src-tauri\binaries"
$buildDir = Join-Path $repoRoot "tmp\pyinstaller"
$distDir = Join-Path $buildDir "dist"
$targetTriple = "x86_64-pc-windows-msvc"

New-Item -ItemType Directory -Force -Path $binaryDir | Out-Null
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null

Push-Location $repoRoot
try {
    uv run pyinstaller `
        --onefile `
        --name nfl-prop-api `
        --distpath $distDir `
        --workpath (Join-Path $buildDir "work") `
        --specpath $buildDir `
        api\sidecar.py

    Copy-Item `
        -LiteralPath (Join-Path $distDir "nfl-prop-api.exe") `
        -Destination (Join-Path $binaryDir "nfl-prop-api-$targetTriple.exe") `
        -Force
}
finally {
    Pop-Location
}

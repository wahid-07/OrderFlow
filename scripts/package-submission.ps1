param(
  [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
  $OutputPath = Join-Path $repositoryRoot 'OrderFlow-submission.zip'
}
else {
  $OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
}

if (Test-Path -LiteralPath $OutputPath) {
  throw "Output already exists; move it or choose another path: $OutputPath"
}

$temporaryRoot = Join-Path $env:TEMP ("orderflow-package-" + [guid]::NewGuid().ToString('N'))
$stageRoot = Join-Path $temporaryRoot 'OrderFlow'
$archiveCreated = $false
$sizeLimit = 25MB
$includedPaths = @(
  '.env.example',
  '.gitignore',
  '.oxlintrc.json',
  'README.md',
  'index.html',
  'package.json',
  'package-lock.json',
  'tsconfig.json',
  'tsconfig.app.json',
  'tsconfig.node.json',
  'vite.config.ts',
  'backend/.env.example',
  'backend/pyproject.toml',
  'backend/app',
  'backend/tests',
  'docs',
  'public',
  'scripts',
  'src'
)

try {
  New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null

  foreach ($relativePath in $includedPaths) {
    $sourcePath = Join-Path $repositoryRoot $relativePath
    if (-not (Test-Path -LiteralPath $sourcePath)) {
      throw "Required submission path is missing: $relativePath"
    }
    $destinationPath = Join-Path $stageRoot $relativePath
    $destinationParent = Split-Path -Parent $destinationPath
    New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Recurse -Force
  }

  $excludedDirectories = @(
    '.git',
    '.pytest_cache',
    '.venv',
    '__pycache__',
    'dist',
    'node_modules',
    'orderflow_api.egg-info',
    'venv'
  )
  Get-ChildItem -LiteralPath $stageRoot -Directory -Recurse -Force |
    Where-Object { $_.Name -in $excludedDirectories } |
    Sort-Object { $_.FullName.Length } -Descending |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }

  Get-ChildItem -LiteralPath $stageRoot -File -Recurse -Force |
    Where-Object {
      $_.Name -eq '.env' -or
      ($_.Name.StartsWith('.env.') -and $_.Name -ne '.env.example') -or
      $_.Extension -in @('.pyc', '.pyo')
    } |
    Remove-Item -Force

  Compress-Archive -Path (Join-Path $stageRoot '*') -DestinationPath $OutputPath -CompressionLevel Optimal
  $archiveCreated = $true
  $archive = Get-Item -LiteralPath $OutputPath

  if ($archive.Length -ge $sizeLimit) {
    Remove-Item -LiteralPath $OutputPath -Force
    $archiveCreated = $false
    throw "Archive is $([math]::Round($archive.Length / 1MB, 2)) MB; the limit is under 25 MB."
  }

  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $zip = [System.IO.Compression.ZipFile]::OpenRead($OutputPath)
  try {
    $unsafeEntries = $zip.Entries | Where-Object {
      $_.FullName -match '(^|/)(node_modules|\.venv|venv|__pycache__|\.pytest_cache|dist|\.git)(/|$)' -or
      $_.FullName -match '(^|/)\.env($|\.)' -and $_.Name -ne '.env.example'
    }
    if ($unsafeEntries) {
      throw 'Archive contains a prohibited generated or environment file.'
    }
  }
  finally {
    $zip.Dispose()
  }

  Write-Output "Created $OutputPath ($([math]::Round($archive.Length / 1MB, 2)) MB)"
}
catch {
  if ($archiveCreated -and (Test-Path -LiteralPath $OutputPath)) {
    Remove-Item -LiteralPath $OutputPath -Force
  }
  throw
}
finally {
  if (Test-Path -LiteralPath $temporaryRoot) {
    Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
  }
}
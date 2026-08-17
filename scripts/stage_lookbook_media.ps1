param(
  [Alias('Source')]
  [AllowNull()]
  [string]$SourceFileArg = $null,
  [string]$Destination = $null
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($SourceFileArg)) {
  $desktopPath = [Environment]::GetFolderPath('Desktop')
  $sourceCandidate = Get-ChildItem -LiteralPath $desktopPath -File -Filter '*.mp4' |
    Where-Object { $_.BaseName -like 'mcm*' } |
    Select-Object -First 1
  if ($null -eq $sourceCandidate) {
    throw "No mcm*.mp4 lookbook video was found on the Desktop. Pass -Source explicitly."
  }
  $SourceFileArg = $sourceCandidate.FullName
}
if ([string]::IsNullOrWhiteSpace($Destination)) {
  $Destination = Join-Path $PSScriptRoot '..\apps\kiosk\public\media\mcm-lookbook-v2.mp4'
}
$sourcePath = [System.IO.Path]::GetFullPath($SourceFileArg)
if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
  throw "Lookbook source file was not found: $sourcePath"
}
$destinationPath = [System.IO.Path]::GetFullPath($Destination)
$expectedSha256 = 'dd40011e9a7767cf82f9cc7d04c15d7d987c86756170f3c98012644ed04c9c89'
$expectedBytes = 5754164
$sourceFile = Get-Item -LiteralPath $sourcePath
$sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($sourceFile.Length -ne $expectedBytes -or $sourceHash -ne $expectedSha256) {
  throw 'The source MP4 does not match the reviewed mcm-lookbook-v2 media identity.'
}
$destinationDirectory = Split-Path -Parent $destinationPath
New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
$hash = (Get-FileHash -LiteralPath $destinationPath -Algorithm SHA256).Hash.ToLowerInvariant()
$file = Get-Item -LiteralPath $destinationPath
if ($file.Length -ne $expectedBytes -or $hash -ne $expectedSha256) {
  throw 'The staged MP4 failed the canonical media identity check.'
}

[pscustomobject]@{
  path = $destinationPath
  bytes = $file.Length
  sha256 = $hash
  git_ignored = $true
}

param(
  [Parameter(Mandatory = $true)]
  [string]$InputZip,

  [Parameter(Mandatory = $true)]
  [string]$OutputZip
)

$ErrorActionPreference = "Stop"

function Find-SignTool {
  $roots = @(
    "${env:ProgramFiles(x86)}\Windows Kits\10\bin",
    "${env:ProgramFiles}\Windows Kits\10\bin"
  ) | Where-Object { $_ -and (Test-Path $_) }

  $tools = foreach ($root in $roots) {
    Get-ChildItem -Path $root -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue
  }

  $tool = $tools |
    Where-Object { $_.FullName -match "\\x64\\signtool\.exe$" } |
    Sort-Object FullName -Descending |
    Select-Object -First 1

  if (-not $tool) {
    $tool = $tools | Sort-Object FullName -Descending | Select-Object -First 1
  }

  if (-not $tool) {
    throw "signtool.exe was not found on this Windows runner"
  }

  return $tool.FullName
}

function Assert-ArchiveHasTrustedSignatures {
  param([Parameter(Mandatory = $true)][string]$ArchivePath)

  $verifyDir = Join-Path $env:RUNNER_TEMP ("signing-verify-" + [Guid]::NewGuid().ToString("N"))
  try {
    New-Item -ItemType Directory -Path $verifyDir -Force | Out-Null
    Expand-Archive -Path $ArchivePath -DestinationPath $verifyDir -Force
    $files = Get-ChildItem -Path $verifyDir -Recurse -File |
      Where-Object { $_.Extension.ToLowerInvariant() -in @(".exe", ".dll", ".msi") }
    if (-not $files) {
      throw "No Windows binaries found inside signed archive: $ArchivePath"
    }
    foreach ($file in $files) {
      $signature = Get-AuthenticodeSignature -FilePath $file.FullName
      if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "Trusted Authenticode validation failed for $($file.Name): $($signature.Status) $($signature.StatusMessage)"
      }
    }
  } finally {
    Remove-Item $verifyDir -Recurse -Force -ErrorAction SilentlyContinue
  }
}

if (-not (Test-Path $InputZip)) {
  throw "Input archive not found: $InputZip"
}

if ($env:SIGN_BASE_URL -and $env:SIGN_API_KEY) {
  Write-Host "Signing archive with SIGN_BASE_URL signing service"
  curl.exe -X POST -F "file=@$InputZip" -H "X-API-KEY: $env:SIGN_API_KEY" -m 900 "$($env:SIGN_BASE_URL.TrimEnd('/'))/sign/" -o $OutputZip
  if ($LASTEXITCODE -ne 0) {
    throw "Signing service request failed with exit code $LASTEXITCODE"
  }
  if (-not (Test-Path $OutputZip) -or ((Get-Item $OutputZip).Length -lt 1)) {
    throw "Signing service did not return a signed archive"
  }
  Assert-ArchiveHasTrustedSignatures -ArchivePath $OutputZip
  exit 0
}

if (-not ($env:WINDOWS_PFX_BASE64 -and $env:WINDOWS_PFX_PASSWORD)) {
  throw "Windows signing is required. Configure a signing service or a publicly trusted code-signing certificate."
}

Write-Host "Signing archive with WINDOWS_PFX_BASE64 certificate"
$workDir = Join-Path $env:RUNNER_TEMP ("signing-" + [Guid]::NewGuid().ToString("N"))
$pfxPath = Join-Path $env:RUNNER_TEMP ("codesign-" + [Guid]::NewGuid().ToString("N") + ".pfx")

try {
  New-Item -ItemType Directory -Path $workDir -Force | Out-Null
  Expand-Archive -Path $InputZip -DestinationPath $workDir -Force
  [IO.File]::WriteAllBytes($pfxPath, [Convert]::FromBase64String($env:WINDOWS_PFX_BASE64))

  $signTool = Find-SignTool
  $timestampUrl = if ($env:SIGN_TIMESTAMP_URL) { $env:SIGN_TIMESTAMP_URL } else { "http://timestamp.digicert.com" }
  $files = Get-ChildItem -Path $workDir -Recurse -File | Where-Object { $_.Extension.ToLowerInvariant() -in @(".exe", ".dll", ".msi") }

  if (-not $files) {
    throw "No Windows binaries found inside archive: $InputZip"
  }

  foreach ($file in $files) {
    Write-Host "Signing $($file.Name)"
    & $signTool sign /fd SHA256 /tr $timestampUrl /td SHA256 /f $pfxPath /p $env:WINDOWS_PFX_PASSWORD $file.FullName
    if ($LASTEXITCODE -ne 0) {
      throw "signtool failed for $($file.Name) with exit code $LASTEXITCODE"
    }
    $signature = Get-AuthenticodeSignature -FilePath $file.FullName
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
      throw "Trusted Authenticode validation failed for $($file.Name): $($signature.Status) $($signature.StatusMessage)"
    }
  }

  if (Test-Path $OutputZip) {
    Remove-Item $OutputZip -Force
  }
  Compress-Archive -Path (Join-Path $workDir "*") -DestinationPath $OutputZip -CompressionLevel Fastest -Force
  Assert-ArchiveHasTrustedSignatures -ArchivePath $OutputZip
} finally {
  Remove-Item $workDir -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item $pfxPath -Force -ErrorAction SilentlyContinue
}

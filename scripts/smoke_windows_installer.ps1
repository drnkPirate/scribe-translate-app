param([Parameter(Mandatory = $true)][string]$Installer)

$ErrorActionPreference = "Stop"
$installDir = Join-Path $env:RUNNER_TEMP "ScribeTranslateSmoke"
$appPath = Join-Path $installDir "Scribe Translate.exe"

if (Test-Path $installDir) {
    Remove-Item -Recurse -Force $installDir
}

Start-Process -FilePath $Installer -ArgumentList "/S", "/D=$installDir" -Wait
if (-not (Test-Path $appPath)) {
    throw "The installer did not create $appPath"
}

$process = Start-Process -FilePath $appPath -PassThru
try {
    $status = $null
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        try {
            $status = Invoke-RestMethod -Uri "http://127.0.0.1:43187/api/status" -TimeoutSec 2
            if ($status.app -eq "scribe-translate") { break }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if ($null -eq $status -or $status.app -ne "scribe-translate") {
        throw "The installed app did not start its local service"
    }
    if ($status.phase -notin @("models_missing", "warming", "ready")) {
        throw "Unexpected service phase: $($status.phase)"
    }
    Write-Output "Installed app smoke check passed: $($status.phase)"
} finally {
    if (-not $process.HasExited) {
        $null = $process.CloseMainWindow()
        if (-not $process.WaitForExit(10000)) {
            Stop-Process -Id $process.Id -Force
        }
    }
    Get-Process "scribe-translate-server" -ErrorAction SilentlyContinue | Stop-Process -Force
}

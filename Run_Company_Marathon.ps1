# Jobiew repository-owned supervisor; no dependency on Downloads.
# Requires a previously authorized, independently maintained local crawler DB.
param(
    [switch]$CheckOnly,
    [switch]$Run,
    [switch]$PermissionConfirmed,
    [string]$CrawlerRoot = '',
    [string]$PythonPath = ''
)
$ErrorActionPreference = 'Stop'
if ($Run -and $CheckOnly) { throw 'Use -CheckOnly OR -Run, not both.' }
if ($Run -and -not $PermissionConfirmed) { throw 'To run authorized crawling, specify -Run -PermissionConfirmed explicitly.' }
$ProjectRoot = $PSScriptRoot
$Marathon = Join-Path $ProjectRoot 'tools\tajrobewiki\TajrobeWiki_Marathon_v7.pyz'
if (-not (Test-Path -LiteralPath $Marathon -PathType Leaf)) { throw "Missing repository-owned Marathon: $Marathon" }
$ExpectedHash = 'ec6d5b098dcdd0c6a7cddd9b38598d2ae03ae3dbd60f56e2df85a6917610e525'
$ActualHash = (Get-FileHash -LiteralPath $Marathon -Algorithm SHA256).Hash
if ($ActualHash -ine $ExpectedHash) { throw "Marathon SHA256 mismatch. Expected=$ExpectedHash Actual=$ActualHash. No crawl launched." }

$CrawlerCandidates = @()
if ($CrawlerRoot) { $CrawlerCandidates += $CrawlerRoot }
elseif ($env:JOBIEW_TAJROBEWIKI_CRAWLER_ROOT) { $CrawlerCandidates += $env:JOBIEW_TAJROBEWIKI_CRAWLER_ROOT }
else {
    $Workspace = Split-Path -Parent $ProjectRoot
    $CrawlerCandidates += (Join-Path $Workspace 'TestProject\tajrobewiki_crawler')
    $CrawlerCandidates += (Join-Path $Workspace 'tajrobewiki_crawler')
}
$RuntimeRoot = $null
foreach ($Candidate in $CrawlerCandidates) {
    if ($Candidate -and (Test-Path -LiteralPath (Join-Path $Candidate 'crawl_site.py') -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $Candidate 'data\tajrobewiki.db') -PathType Leaf)) {
        $RuntimeRoot = (Resolve-Path -LiteralPath $Candidate).Path
        break
    }
}
if (-not $RuntimeRoot) {
    throw 'Crawler runtime with crawl_site.py and data\tajrobewiki.db not found. Supply -CrawlerRoot FULL_PATH. Existing DB/checkpoint will not be moved.'
}

$Candidates = @()
if ($PythonPath) { $Candidates += $PythonPath }
else {
    if ($env:VIRTUAL_ENV) { $Candidates += (Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe') }
    $Candidates += (Join-Path $ProjectRoot '.venv\Scripts\python.exe')
    $Candidates += (Join-Path $RuntimeRoot '.venv\Scripts\python.exe')
    $Candidates += (Join-Path (Split-Path -Parent $RuntimeRoot) '.venv\Scripts\python.exe')
    $Candidates += (Join-Path $ProjectRoot 'venv\Scripts\python.exe')
    $Cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($Cmd -and $Cmd.Source) { $Candidates += $Cmd.Source }
}
$Python = $null
foreach ($Candidate in ($Candidates | Select-Object -Unique)) {
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { continue }
    try {
        $OldPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            if ($Run) { & $Candidate -c 'import bs4, requests' *> $null }
            else { & $Candidate -c 'import sys' *> $null }
            $Code = $LASTEXITCODE
        } finally { $ErrorActionPreference = $OldPreference }
        if ($Code -eq 0) { $Python = $Candidate; break }
    } catch {}
}
if (-not $Python) {
    throw 'No suitable Python found. Supply -PythonPath FULL_PATH_TO_PYTHON.EXE. For -Run it must have requests and bs4.'
}
Write-Host "Jobiew project: $ProjectRoot"
Write-Host "Marathon file: $Marathon"
Write-Host "Existing crawler/checkpoint: $RuntimeRoot"
Write-Host "Python: $Python"

# Run the package's pinned crawl_site.py/source hash check BEFORE any HTTP requests.
Push-Location $RuntimeRoot
try {
    & $Python $Marathon --status --project-root $RuntimeRoot
    if ($LASTEXITCODE -ne 0) { throw "Marathon preflight/status failed (code $LASTEXITCODE). Crawler source must match its reviewed version; do not bypass checksum." }
} finally { Pop-Location }
if (-not $Run) {
    Write-Host 'CHECK OK: no crawling started; no checkpoint changes.'
    return
}

$SupervisorDir = Join-Path $RuntimeRoot 'reports\company_marathon_v7\continuous'
$StatusPath = Join-Path $RuntimeRoot 'reports\company_marathon_v7\status.json'
$PauseMarker = Join-Path $SupervisorDir 'pause.txt'
New-Item -ItemType Directory -Force -Path $SupervisorDir | Out-Null
$Mutex = New-Object System.Threading.Mutex($false, 'Global\JobiewCompanyMarathonContinuous')
$Locked = $false
try {
    try { $Locked = $Mutex.WaitOne(0, $false) }
    catch [System.Threading.AbandonedMutexException] { $Locked = $true }
    if (-not $Locked) { throw 'Another Jobiew marathon supervisor is running.' }
    $Round = 0
    while ($true) {
        if (Test-Path -LiteralPath $PauseMarker) { Write-Host "PAUSED by marker: $PauseMarker"; break }
        $Round++
        $Stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
        $Log = Join-Path $SupervisorDir ("marathon_{0}_{1}.log" -f $Stamp, $Round)
        Write-Host "Starting authorized 48h window. Log: $Log"
        Push-Location $RuntimeRoot
        try {
            $OldPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = 'Continue'
                & $Python $Marathon --run --project-root $RuntimeRoot --hours 48 --batch-size 12 --pause 30 --retries 1 --retry-wait 60 --cooldown-seconds 60 --permission-confirmed 2>&1 | Tee-Object -FilePath $Log
                $Code = $LASTEXITCODE
            } finally { $ErrorActionPreference = $OldPreference }
        } finally { Pop-Location }
        if ($Code -ne 0) { throw "SAFETY STOP: Marathon failed (code $Code). Check $Log before retry." }
        if (-not (Test-Path -LiteralPath $StatusPath -PathType Leaf)) { throw "Marathon status missing: $StatusPath" }
        $Report = Get-Content -LiteralPath $StatusPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $Outcome = [string]$Report.outcome
        Write-Host "Marathon outcome: $Outcome"
        if ($Outcome -in @('all_discovered_company_pages_processed','listings_complete')) { Write-Host 'COMPLETE: listing crawl finished.'; break }
        if ($Outcome -eq 'interrupted') { Write-Host 'STOP: operator interruption.'; break }
        if ($Outcome -ne 'time_limit') { throw "SAFETY STOP: unexpected outcome '$Outcome'" }
        Write-Host 'Window ended; resuming from existing SQLite checkpoint after 5 minutes.'
        Start-Sleep -Seconds 300
    }
} finally {
    if ($Locked) { $Mutex.ReleaseMutex() }
    $Mutex.Dispose()
}

param(
    [string]$DshRoot = "",
    [string]$AgentId = "",
    [string]$HostTag = "",
    [int]$WinPort = 3081,
    [string]$NodeBin = "",
    [string]$MailboxRoot = "",
    [string]$MagpieKey = ""
)
$ErrorActionPreference = "Stop"
if (-not $MagpieKey) { $MagpieKey = if ($env:MAGPIE_GATEWAY_KEY) { $env:MAGPIE_GATEWAY_KEY } else { "magpie" } }
if (-not $DshRoot) { $DshRoot = (Get-Location).Path }
if (-not $HostTag) { $HostTag = $env:COMPUTERNAME.ToLower() }
if (-not $AgentId) { $AgentId = "dsh-$HostTag-win" }
if (-not $MailboxRoot) { $MailboxRoot = Join-Path $env:USERPROFILE ".agents-mailbox" }
if (-not $NodeBin) { $NodeBin = (Get-Command node -ErrorAction Stop).Source }
$tokenDir = Join-Path $MailboxRoot "dsh-hosts"
New-Item -ItemType Directory -Force -Path $tokenDir | Out-Null
$occupied = Get-NetTCPConnection -LocalPort $WinPort -State Listen -ErrorAction SilentlyContinue
if ($occupied) {
    $opid = ($occupied | Select-Object -First 1).OwningProcess
    Write-Error "port $WinPort occupied by pid=$opid, stop it first: taskkill /PID $opid /T /F"
    exit 1
}
$log = Join-Path $env:TEMP "dsh-host-$AgentId.log"
$logErr = Join-Path $env:TEMP "dsh-host-$AgentId.err.log"
Remove-Item $log, $logErr -ErrorAction SilentlyContinue
$env:MAGPIE_GATEWAY_KEY = $MagpieKey
$proc = Start-Process -FilePath $NodeBin -ArgumentList @("apps\cli\lib\bin.js", "web", "--no-open", "--port", "$WinPort") -WorkingDirectory $DshRoot -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $logErr -PassThru
$token = ""
for ($i = 0; $i -lt 60; $i++) {
    if ($proc.HasExited) {
        Write-Error "dsh host exited early, see $log $logErr"
        exit 1
    }
    Start-Sleep -Seconds 1
    foreach ($probe in @($log, $logErr)) {
        if (Test-Path $probe) {
            $m = Select-String -Path $probe -Pattern "token=([A-Za-z0-9_-]+)" -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($m) { $token = $m.Matches[0].Groups[1].Value; break }
        }
    }
    if ($token) { break }
}
if (-not $token) {
    & taskkill.exe /PID $proc.Id /T /F | Out-Null
    Write-Error "no launch token in 60s, host pid=$($proc.Id) killed, see $log $logErr"
    exit 1
}
$tokenPath = Join-Path $tokenDir "$AgentId.token"
$cookiePath = Join-Path $tokenDir "$AgentId.cookie"
Set-Content -Path $tokenPath -Value $token -NoNewline
Remove-Item $cookiePath -ErrorAction SilentlyContinue
& icacls.exe $tokenPath /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
Write-Output "dsh win host agent_id=$AgentId port=$WinPort pid=$($proc.Id) token -> $tokenPath"
Write-Output "stop: taskkill /PID $($proc.Id) /T /F"

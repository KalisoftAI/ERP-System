$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$values = @{}
if (Test-Path -LiteralPath ".env") {
    foreach ($line in Get-Content -LiteralPath ".env") {
        $text = $line.Trim()
        if (-not $text -or $text.StartsWith("#") -or $text -notmatch "^([^=]+)=(.*)$") {
            continue
        }
        $key = $Matches[1].Trim()
        $value = $Matches[2].Trim().Trim('"').Trim("'")
        $values[$key] = $value
    }
}

function Get-Value {
    param([string]$Key, [string]$Default = "")
    if ($values.ContainsKey($Key) -and $values[$Key]) {
        return $values[$Key]
    }
    $current = [Environment]::GetEnvironmentVariable($Key)
    if ($current) {
        return $current
    }
    return $Default
}

$mode = (Get-Value "DEVICE_MODE" "tcp_client").ToLowerInvariant()
$deviceId = Get-Value "DEVICE_ID" "USR-TCP232-302"
$expectedMac = (Get-Value "DEVICE_MAC" "D4:AD:20:DB:E8:C9").ToUpperInvariant()
$hostName = Get-Value "DEVICE_HOST" "192.168.0.7"
$portText = Get-Value "DEVICE_PORT" ""

Write-Host "Bridge directory: $PSScriptRoot"
Write-Host "Mode: $mode"
Write-Host "Device ID: $deviceId"
Write-Host "Expected MAC: $expectedMac"

if ($mode -eq "simulation") {
    Write-Host "Simulation mode selected; no TCP or ARP check is required."
    exit 0
}

if (-not $portText) {
    throw "DEVICE_PORT is not set. Read the USR TCP Server Local Port Number and set DEVICE_PORT before testing."
}

$port = 0
if (-not [int]::TryParse($portText, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
    throw "DEVICE_PORT must be an integer between 1 and 65535; got '$portText'."
}

$adapters = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -ne '127.0.0.1' } |
    Select-Object IPAddress, InterfaceAlias
if ($adapters) {
    $adapters | Format-Table -AutoSize | Out-String | Write-Host
} else {
    Write-Host "No IPv4 adapter addresses were found."
}

Write-Host "Target: ${hostName}:$port"

$pingOk = Test-Connection -ComputerName $hostName -Count 1 -Quiet -ErrorAction SilentlyContinue
Write-Host "PING: $pingOk"

$arpLine = arp -a | Select-String -SimpleMatch $hostName | Select-Object -First 1
if ($arpLine) {
    $arpText = $arpLine.ToString().Trim()
    Write-Host "ARP: $arpText"
    if ($arpText -match '([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}') {
        $actualMac = $Matches[0].Replace('-', ':').ToUpperInvariant()
        Write-Host "MAC: $actualMac"
        Write-Host "MAC_MATCH: $($actualMac -eq $expectedMac)"
    } else {
        Write-Host "MAC: not found in ARP output"
    }
} else {
    Write-Host "ARP: no entry for $hostName"
}

$tcpOk = Test-NetConnection -ComputerName $hostName -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue
Write-Host "TCP_$($port): $tcpOk"
if ($tcpOk -ne $true) {
    Write-Host "TCP check failed. Verify USR work mode, Local Port, power, cable, subnet and firewall."
}

$gcsUpload = (Get-Value "GCS_UPLOAD_ENABLED" "false").ToLowerInvariant()
if ($gcsUpload -eq "true") {
    $bucket = Get-Value "GCS_BUCKET" "kalisoftai-datahub"
    $prefix = Get-Value "GCS_LOG_PREFIX" "Kalika_inventory/Logs"
    $environment = Get-Value "WEIGHING_ENVIRONMENT" "local"
    $credentials = Get-Value "GOOGLE_APPLICATION_CREDENTIALS" ""
    $credentialsOk = "NOT_SET"
    if ($credentials) {
        $credentialPath = $credentials
        if (-not [IO.Path]::IsPathRooted($credentialPath)) {
            $credentialPath = Join-Path $PSScriptRoot $credentialPath
        }
        $credentialsOk = Test-Path -LiteralPath $credentialPath
    }
    Write-Host "GCS: gs://$bucket/$prefix/weighing/$environment/$deviceId/YYYY/MM/DD/<filename>.jsonl"
    Write-Host "GCS_CREDENTIALS_OK: $credentialsOk"
} else {
    Write-Host "GCS: disabled (GCS_UPLOAD_ENABLED=false)"
}

[CmdletBinding()]
param(
    [string]$ServerDirectory = "mc-server",
    [string]$ServerJar = "server.jar",
    [string]$MinecraftHost = "127.0.0.1",
    [int]$MinecraftPort = 25565,
    [string]$Username = "Singularity",
    [int]$BridgePort = 30000,
    [int]$ServerWaitSeconds = 180,
    [int]$BridgeWaitSeconds = 45,
    [switch]$KeepProcesses
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$serverRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $ServerDirectory))
$jarPath = Join-Path $serverRoot $ServerJar
$eulaPath = Join-Path $serverRoot "eula.txt"
$propertiesPath = Join-Path $serverRoot "server.properties"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runtimeLogRoot = Join-Path $repoRoot "logs\benchmarks\runtime"
$preflightPath = Join-Path $repoRoot "logs\benchmarks\m1_preflight_$timestamp.json"
$serverProcess = $null
$bridgeProcess = $null

function Test-TcpEndpoint {
    param([string]$HostName, [int]$Port, [int]$TimeoutMs = 1000)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $pending = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne($TimeoutMs)) {
            return $false
        }
        $client.EndConnect($pending)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Get-ServerProperty {
    param([string]$Path, [string]$Name)

    $match = Get-Content -LiteralPath $Path | Where-Object {
        $_ -match "^\s*$([regex]::Escape($Name))\s*="
    } | Select-Object -Last 1
    if (-not $match) {
        return $null
    }
    return ($match -split "=", 2)[1].Trim()
}

function Wait-ForTcpEndpoint {
    param([string]$HostName, [int]$Port, [int]$TimeoutSeconds)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-TcpEndpoint -HostName $HostName -Port $Port) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Get-BridgeHealth {
    param([string]$HostName, [int]$Port)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $client.ReceiveTimeout = 2000
        $client.SendTimeout = 2000
        $client.Connect($HostName, $Port)
        $stream = $client.GetStream()
        $request = [System.Text.Encoding]::UTF8.GetBytes('{"command":"health","params":{}}' + "`n")
        $stream.Write($request, 0, $request.Length)
        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $false, 1024, $true)
        $line = $reader.ReadLine()
        if (-not $line) {
            return $null
        }
        return $line | ConvertFrom-Json
    }
    catch {
        return $null
    }
    finally {
        $client.Dispose()
    }
}

function Wait-ForBridgeSession {
    param([string]$HostName, [int]$Port, [int]$TimeoutSeconds)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $health = Get-BridgeHealth -HostName $HostName -Port $Port
        if ($health -and $health.success -eq $true -and $health.bridge -eq $true -and $health.bot_ready -eq $true) {
            return $health
        }
        Start-Sleep -Seconds 1
    }
    return $null
}

function Stop-OwnedProcess {
    param($Process)

    if ($Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id
        $Process.WaitForExit(10000) | Out-Null
    }
}

function Assert-File {
    param([string]$Path, [string]$Message)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw $Message
    }
}

Push-Location $repoRoot
try {
    New-Item -ItemType Directory -Force -Path $runtimeLogRoot | Out-Null
    Assert-File -Path $jarPath -Message "M1 runtime blocked: $jarPath is missing. Place a Minecraft 1.20.4 Paper server jar there."
    Assert-File -Path $eulaPath -Message "M1 runtime blocked: $eulaPath is missing. Start the server once, read the Minecraft EULA, and edit eula.txt manually. This script never accepts the EULA."
    if (-not (Select-String -LiteralPath $eulaPath -Pattern '^\s*eula\s*=\s*true\s*$' -Quiet)) {
        throw "M1 runtime blocked: eula=true is not present in $eulaPath. Read and accept the Minecraft EULA manually; this script never edits eula.txt."
    }
    Assert-File -Path $propertiesPath -Message "M1 runtime blocked: $propertiesPath is missing. Generate it with the server, then configure the fixed M1 protocol."

    $seed = Get-ServerProperty -Path $propertiesPath -Name "level-seed"
    $onlineMode = Get-ServerProperty -Path $propertiesPath -Name "online-mode"
    $configuredPort = Get-ServerProperty -Path $propertiesPath -Name "server-port"
    if ($seed -ne "12345") {
        throw "M1 runtime blocked: server.properties must contain level-seed=12345; observed '$seed'."
    }
    if ($onlineMode -ne "false") {
        throw "M1 runtime blocked: server.properties must contain online-mode=false for the configured offline Mineflayer identity."
    }
    if ($configuredPort -and [int]$configuredPort -ne $MinecraftPort) {
        throw "M1 runtime blocked: server.properties uses port $configuredPort but this run requested $MinecraftPort."
    }
    if (Test-TcpEndpoint -HostName $MinecraftHost -Port $MinecraftPort) {
        throw "M1 runtime blocked: $MinecraftHost`:$MinecraftPort is already occupied. Stop the existing service so this script owns the evidence runtime."
    }
    if (Test-TcpEndpoint -HostName "127.0.0.1" -Port $BridgePort) {
        throw "M1 runtime blocked: bridge port $BridgePort is already occupied. Choose an unused -BridgePort; no process will be stopped automatically."
    }

    $serverStdout = Join-Path $runtimeLogRoot "m1_server_$timestamp.stdout.log"
    $serverStderr = Join-Path $runtimeLogRoot "m1_server_$timestamp.stderr.log"
    $serverProcess = Start-Process -FilePath "java" -ArgumentList @("-Xms1G", "-Xmx2G", "-jar", $ServerJar, "nogui") -WorkingDirectory $serverRoot -RedirectStandardOutput $serverStdout -RedirectStandardError $serverStderr -WindowStyle Hidden -PassThru
    if (-not (Wait-ForTcpEndpoint -HostName $MinecraftHost -Port $MinecraftPort -TimeoutSeconds $ServerWaitSeconds)) {
        throw "M1 runtime blocked: Minecraft did not listen on $MinecraftHost`:$MinecraftPort within $ServerWaitSeconds seconds. Inspect $serverStdout and $serverStderr."
    }

    $bridgeStdout = Join-Path $runtimeLogRoot "m1_bridge_$timestamp.stdout.log"
    $bridgeStderr = Join-Path $runtimeLogRoot "m1_bridge_$timestamp.stderr.log"
    $bridgeArguments = @(
        "src/bot/bot_server.js",
        "--host", $MinecraftHost,
        "--port", $MinecraftPort,
        "--username", $Username,
        "--version", "1.20.4",
        "--bridge-port", $BridgePort
    )
    $bridgeProcess = Start-Process -FilePath "node" -ArgumentList $bridgeArguments -WorkingDirectory $repoRoot -RedirectStandardOutput $bridgeStdout -RedirectStandardError $bridgeStderr -WindowStyle Hidden -PassThru
    $health = Wait-ForBridgeSession -HostName "127.0.0.1" -Port $BridgePort -TimeoutSeconds $BridgeWaitSeconds
    if (-not $health) {
        throw "M1 runtime blocked: the Singularity bridge did not report bot_ready=true within $BridgeWaitSeconds seconds. Inspect $bridgeStdout and $bridgeStderr."
    }
    if ([string]$health.version -ne "1.20.4") {
        throw "M1 runtime blocked: the spawned bot reports Minecraft version '$($health.version)', expected 1.20.4."
    }

    & python -m singularity.main preflight --host $MinecraftHost --port $MinecraftPort --username $Username --bridge-host 127.0.0.1 --bridge-port $BridgePort --output $preflightPath
    if ($LASTEXITCODE -ne 0) {
        throw "M1 runtime preflight failed. Evidence: $preflightPath"
    }

    Write-Host "M1 runtime preflight passed."
    Write-Host "Evidence: $preflightPath"
    Write-Host "Next gate: implement and verify canonical per-task world/inventory reset before collecting BM-001..005 acceptance runs."
    if ($KeepProcesses) {
        Write-Host "Minecraft PID: $($serverProcess.Id); bridge PID: $($bridgeProcess.Id)"
        $serverProcess = $null
        $bridgeProcess = $null
    }
}
finally {
    Stop-OwnedProcess -Process $bridgeProcess
    Stop-OwnedProcess -Process $serverProcess
    Pop-Location
}

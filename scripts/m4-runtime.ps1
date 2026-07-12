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
    [ValidateSet("BM-011")]
    [string]$TaskId = "BM-011",
    [double]$MaxDurationSeconds = 1200,
    [int]$MaxGoals = 24,
    [int]$MaxCycles = 40
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$serverRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $ServerDirectory))
$jarPath = Join-Path $serverRoot $ServerJar
$eulaPath = Join-Path $serverRoot "eula.txt"
$propertiesPath = Join-Path $serverRoot "server.properties"
$protocolPath = Join-Path $repoRoot "src\singularity\data\m4_protocol.json"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$episodeId = "m4_episode_${timestamp}_$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$levelName = "${episodeId}_bm011"
$relativeOutput = "logs\benchmarks\m4\$episodeId"
$outputRoot = Join-Path $repoRoot $relativeOutput
$runtimeLogRoot = Join-Path $repoRoot "logs\benchmarks\runtime"
$blockerPath = Join-Path $repoRoot "logs\benchmarks\m4\m4_runtime_blocker_${timestamp}.json"
$serverProcess = $null
$bridgeProcess = $null
$originalServerProperties = $null
$originalServerPropertiesBytes = $null
$serverPropertiesModified = $false
$originalApiKey = [Environment]::GetEnvironmentVariable("SINGULARITY_LLM_API_KEY", "Process")
$originalBaseUrl = [Environment]::GetEnvironmentVariable("SINGULARITY_LLM_BASE_URL", "Process")
$originalPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")

function Assert-File {
    param([string]$Path, [string]$Message)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw $Message }
}

function Test-TcpEndpoint {
    param([string]$HostName, [int]$Port, [int]$TimeoutMs = 1000)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $pending = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne($TimeoutMs)) { return $false }
        $client.EndConnect($pending)
        return $true
    }
    catch { return $false }
    finally { $client.Dispose() }
}

function Wait-ForTcpEndpoint {
    param([string]$HostName, [int]$Port, [int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-TcpEndpoint -HostName $HostName -Port $Port) { return $true }
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
        $bytes = [System.Text.Encoding]::UTF8.GetBytes('{"command":"health","params":{}}' + "`n")
        $stream.Write($bytes, 0, $bytes.Length)
        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $false, 1024, $true)
        $line = $reader.ReadLine()
        if (-not $line) { return $null }
        return $line | ConvertFrom-Json
    }
    catch { return $null }
    finally { $client.Dispose() }
}

function Wait-ForBridgeSession {
    param([string]$HostName, [int]$Port, [int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $health = Get-BridgeHealth -HostName $HostName -Port $Port
        if ($health -and $health.success -eq $true -and $health.bot_ready -eq $true) { return $health }
        Start-Sleep -Seconds 1
    }
    return $null
}

function Get-ServerProperty {
    param([string]$Path, [string]$Name)
    $match = Get-Content -LiteralPath $Path | Where-Object {
        $_ -match "^\s*$([regex]::Escape($Name))\s*="
    } | Select-Object -Last 1
    if (-not $match) { return $null }
    return ($match -split "=", 2)[1].Trim()
}

function Set-ServerPropertyValue {
    param([string]$Content, [string]$Name, [string]$Value)
    $pattern = "(?m)^\s*$([regex]::Escape($Name))\s*=.*$"
    $replacement = "$Name=$Value"
    if ([regex]::IsMatch($Content, $pattern)) {
        return [regex]::Replace($Content, $pattern, $replacement)
    }
    return $Content.TrimEnd() + [Environment]::NewLine + $replacement + [Environment]::NewLine
}

function Get-ConfiguredApiKey {
    foreach ($name in @("SINGULARITY_LLM_API_KEY", "OPENAI_API_KEY")) {
        foreach ($scope in @("Process", "User", "Machine")) {
            $value = [Environment]::GetEnvironmentVariable($name, $scope)
            if (-not [string]::IsNullOrWhiteSpace($value)) { return $value }
        }
    }
    return ""
}

function Stop-OwnedProcess {
    param($Process)
    if ($Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id
        $Process.WaitForExit(10000) | Out-Null
    }
}

Push-Location $repoRoot
try {
    Assert-File $jarPath "M4 runtime blocked: server jar missing at $jarPath."
    Assert-File $eulaPath "M4 runtime blocked: eula.txt is missing."
    Assert-File $propertiesPath "M4 runtime blocked: server.properties is missing."
    Assert-File $protocolPath "M4 runtime blocked: m4_protocol.json is missing."
    if (-not (Select-String -LiteralPath $eulaPath -Pattern '^\s*eula\s*=\s*true\s*$' -Quiet)) {
        throw "M4 runtime blocked: eula=true is not present."
    }
    $protocol = Get-Content -LiteralPath $protocolPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $bm011 = @($protocol.tasks | Where-Object { $_.id -eq "BM-011" })[0]
    if (
        $MaxDurationSeconds -ne [double]$bm011.max_duration_s -or
        $MaxGoals -ne [int]$protocol.limits.max_autonomous_goals -or
        $MaxCycles -ne [int]$protocol.limits.max_cycles_per_goal
    ) {
        throw "M4 runtime blocked: BM-011 requires exact fixed limits duration=$($bm011.max_duration_s), goals=$($protocol.limits.max_autonomous_goals), cycles=$($protocol.limits.max_cycles_per_goal)."
    }
    $serverJarSha256 = (Get-FileHash -LiteralPath $jarPath -Algorithm SHA256).Hash.ToLower()
    if ($serverJarSha256 -ne [string]$protocol.server_jar_sha256) {
        throw "M4 runtime blocked: server jar SHA-256 does not match $($protocol.server_build)."
    }
    if ((Get-ServerProperty $propertiesPath "level-seed") -ne [string]$protocol.world_seed) {
        throw "M4 runtime blocked: server.properties must use level-seed=$($protocol.world_seed)."
    }
    if ((Get-ServerProperty $propertiesPath "online-mode") -ne "false") {
        throw "M4 runtime blocked: server.properties must use online-mode=false."
    }
    $opsPath = Join-Path $serverRoot "ops.json"
    Assert-File $opsPath "M4 runtime blocked: ops.json is missing."
    $operators = @(Get-Content -LiteralPath $opsPath -Raw -Encoding UTF8 | ConvertFrom-Json)
    if (-not ($operators | Where-Object { $_.name -eq $Username })) {
        throw "M4 runtime blocked: $Username is not an operator."
    }
    $apiKey = Get-ConfiguredApiKey
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        throw "M4 runtime blocked: LLM credential is missing."
    }
    foreach ($suffix in @("", "_nether", "_the_end")) {
        $worldPath = Join-Path $serverRoot ($levelName + $suffix)
        if (Test-Path -LiteralPath $worldPath) { throw "M4 runtime refuses reused world $worldPath." }
    }
    if (Test-Path -LiteralPath $outputRoot) { throw "M4 runtime refuses existing evidence directory $outputRoot." }
    if (Test-TcpEndpoint $MinecraftHost $MinecraftPort) { throw "M4 runtime blocked: Minecraft port is occupied." }
    if (Test-TcpEndpoint "127.0.0.1" $BridgePort) { throw "M4 runtime blocked: bridge port is occupied." }

    New-Item -ItemType Directory -Force -Path $runtimeLogRoot | Out-Null
    $originalServerPropertiesBytes = [System.IO.File]::ReadAllBytes($propertiesPath)
    $originalServerProperties = [System.Text.Encoding]::UTF8.GetString($originalServerPropertiesBytes)
    $updated = $originalServerProperties
    foreach ($entry in ([ordered]@{
        "level-name" = $levelName
        "level-seed" = [string]$protocol.world_seed
        "server-port" = [string]$MinecraftPort
        "online-mode" = "false"
        "gamemode" = [string]$protocol.game_mode
        "difficulty" = [string]$protocol.difficulty
        "spawn-monsters" = "true"
    }).GetEnumerator()) {
        $updated = Set-ServerPropertyValue $updated $entry.Key $entry.Value
    }
    [System.IO.File]::WriteAllText($propertiesPath, $updated, [System.Text.UTF8Encoding]::new($false))
    $serverPropertiesModified = $true

    $serverStdout = Join-Path $runtimeLogRoot "m4_server_${episodeId}.stdout.log"
    $serverStderr = Join-Path $runtimeLogRoot "m4_server_${episodeId}.stderr.log"
    $serverProcess = Start-Process -FilePath "java" -ArgumentList @("-Xms1G", "-Xmx2G", "-jar", $ServerJar, "nogui") -WorkingDirectory $serverRoot -RedirectStandardOutput $serverStdout -RedirectStandardError $serverStderr -WindowStyle Hidden -PassThru
    if (-not (Wait-ForTcpEndpoint $MinecraftHost $MinecraftPort $ServerWaitSeconds)) {
        throw "M4 runtime blocked: Minecraft did not become ready."
    }

    $bridgeStdout = Join-Path $runtimeLogRoot "m4_bridge_${episodeId}.stdout.log"
    $bridgeStderr = Join-Path $runtimeLogRoot "m4_bridge_${episodeId}.stderr.log"
    $bridgeArgs = @(
        "src/bot/bot_server.js",
        "--host", $MinecraftHost,
        "--port", $MinecraftPort,
        "--username", $Username,
        "--version", [string]$protocol.minecraft_version,
        "--bridge-port", $BridgePort,
        "--benchmark-seed", [string]$protocol.world_seed,
        "--benchmark-episode", $episodeId,
        "--benchmark-level-name", $levelName,
        "--benchmark-server-jar-sha256", $serverJarSha256
    )
    $bridgeProcess = Start-Process -FilePath "node" -ArgumentList $bridgeArgs -WorkingDirectory $repoRoot -RedirectStandardOutput $bridgeStdout -RedirectStandardError $bridgeStderr -WindowStyle Hidden -PassThru
    if (-not (Wait-ForBridgeSession "127.0.0.1" $BridgePort $BridgeWaitSeconds)) {
        throw "M4 runtime blocked: bridge did not report bot_ready=true."
    }

    $env:SINGULARITY_LLM_API_KEY = $apiKey
    $env:SINGULARITY_LLM_BASE_URL = [string]$protocol.llm.base_url
    $env:PYTHONPATH = Join-Path $repoRoot "src"
    & python scripts/m4_episode_runner.py --task-id $TaskId --host $MinecraftHost --port $MinecraftPort --username $Username --bridge-host 127.0.0.1 --bridge-port $BridgePort --episode-id $episodeId --level-name $levelName --output-dir $relativeOutput --max-duration $MaxDurationSeconds --max-goals $MaxGoals --max-cycles $MaxCycles --fresh-level
    if ($LASTEXITCODE -ne 0) { throw "M4 episode runner failed with exit code $LASTEXITCODE." }

    $preparationPath = Join-Path $outputRoot "preparation.json"
    Assert-File $preparationPath "M4 runner did not write preparation evidence."
    $preparation = Get-Content -LiteralPath $preparationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host "M4 episode complete: $episodeId"
    Write-Host "G2 passed: $($preparation.g2_passed); BM-011 eligible: $($preparation.evidence_eligible)"
    Write-Host "Evidence: $relativeOutput"
}
catch {
    $blocker = [ordered]@{
        type = "m4_runtime_blocker"
        schema_version = 1
        generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        task_id = $TaskId
        episode_id = $episodeId
        level_name = $levelName
        blocker = [string]$_.Exception.Message
        evidence_dir = $relativeOutput
        counts_toward_bm011_success = $false
    }
    if (-not (Test-Path -LiteralPath $blockerPath)) {
        [System.IO.File]::WriteAllText($blockerPath, ($blocker | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
        Write-Host "Blocker evidence: $blockerPath"
    }
    throw
}
finally {
    $cleanupErrors = [System.Collections.Generic.List[string]]::new()
    foreach ($ownedProcess in @($bridgeProcess, $serverProcess)) {
        try { Stop-OwnedProcess $ownedProcess }
        catch { $cleanupErrors.Add([string]$_.Exception.Message) }
    }
    try {
        if ($serverPropertiesModified -and $null -ne $originalServerPropertiesBytes) {
            [System.IO.File]::WriteAllBytes($propertiesPath, $originalServerPropertiesBytes)
        }
    }
    catch { $cleanupErrors.Add([string]$_.Exception.Message) }
    $environmentRestore = [ordered]@{
        "SINGULARITY_LLM_API_KEY" = $originalApiKey
        "SINGULARITY_LLM_BASE_URL" = $originalBaseUrl
        "PYTHONPATH" = $originalPythonPath
    }
    foreach ($entry in $environmentRestore.GetEnumerator()) {
        try { [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process") }
        catch { $cleanupErrors.Add([string]$_.Exception.Message) }
    }
    try { Pop-Location }
    catch { $cleanupErrors.Add([string]$_.Exception.Message) }
    if ($cleanupErrors.Count -gt 0) {
        Write-Warning ("M4 runtime cleanup issues: " + ($cleanupErrors -join "; "))
    }
}

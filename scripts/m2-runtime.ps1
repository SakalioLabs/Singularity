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
    [ValidateSet("BM-006", "BM-007", "BM-008", "BM-009", "BM-010")]
    [string]$TaskId,
    [ValidateSet("default", "baseline", "candidate")]
    [string]$Arm = "default",
    [string]$SkillId = "",
    [string]$ExperimentId = "",
    [string]$PairId = "",
    [string]$ReplicateId = "",
    [string]$SkillStoragePath = "workspace/skills",
    [string[]]$SkillRuntimeDefaultGate = @(),
    [string]$OutputPath = "",
    [switch]$HarnessSmoke,
    [switch]$TemplateSmoke,
    [switch]$KeepProcesses
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$serverRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $ServerDirectory))
$jarPath = Join-Path $serverRoot $ServerJar
$eulaPath = Join-Path $serverRoot "eula.txt"
$propertiesPath = Join-Path $serverRoot "server.properties"
$protocolPath = Join-Path $repoRoot "src\singularity\data\m2_protocol.json"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$HarnessSmoke = [bool]($HarnessSmoke -or $TemplateSmoke)
$episodeId = "m2_episode_${timestamp}_$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$runLabel = $TaskId.ToLower().Replace("-", "_")
$levelName = "${episodeId}_${runLabel}"
$modeLabel = if ($TemplateSmoke) { "template" } elseif ($HarnessSmoke) { "harness" } else { $Arm }
$artifactLabel = "${TaskId}_${modeLabel}_$timestamp"
$runtimeLogRoot = Join-Path $repoRoot "logs\benchmarks\runtime"
$preflightPath = Join-Path $repoRoot "logs\benchmarks\m2_preflight_$artifactLabel.json"
$manifestPath = Join-Path $repoRoot "logs\benchmarks\m2_runtime_manifest_$artifactLabel.json"
$blockerPath = Join-Path $repoRoot "logs\benchmarks\m2_runtime_blocker_$artifactLabel.json"
$defaultResult = if ($HarnessSmoke) {
    Join-Path $repoRoot "logs\benchmarks\m2_harness_smoke_$artifactLabel.json"
} else {
    Join-Path $repoRoot "logs\benchmarks\m2_benchmark_$artifactLabel.json"
}
$benchmarkPath = if ($OutputPath) {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputPath))
} else {
    $defaultResult
}
$serverProcess = $null
$bridgeProcess = $null
$originalServerProperties = $null
$serverPropertiesModified = $false

function Assert-File {
    param([string]$Path, [string]$Message)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw $Message
    }
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

function Get-ConfiguredApiKey {
    foreach ($name in @("SINGULARITY_LLM_API_KEY", "OPENAI_API_KEY")) {
        foreach ($scope in @("Process", "User", "Machine")) {
            $value = [Environment]::GetEnvironmentVariable($name, $scope)
            if (-not [string]::IsNullOrWhiteSpace($value)) { return $value }
        }
    }
    return ""
}

Push-Location $repoRoot
try {
    if (-not $TaskId) { throw "M2 runtime requires exactly one -TaskId." }
    if ($TemplateSmoke -and $TaskId -ne "BM-010") {
        throw "M2 template smoke is only defined for BM-010."
    }
    if ($HarnessSmoke -and ($Arm -ne "default" -or $SkillId -or $ExperimentId -or $PairId -or $ReplicateId)) {
        throw "M2 harness smoke does not accept paired-arm or skill arguments."
    }
    if ($Arm -eq "candidate" -and -not $SkillId) {
        throw "M2 candidate arm requires -SkillId."
    }
    if ($Arm -in @("baseline", "candidate") -and (-not $PairId -or -not $ReplicateId)) {
        throw "M2 paired arms require both -PairId and -ReplicateId."
    }
    if ($Arm -eq "default" -and ($PairId -or $ReplicateId)) {
        throw "M2 default arm does not accept paired-run metadata."
    }
    if ($Arm -ne "candidate" -and $SkillId) {
        throw "-SkillId is only valid for the candidate arm."
    }
    if ($Arm -eq "candidate" -and $SkillRuntimeDefaultGate.Count -lt 1) {
        throw "M2 candidate arm requires at least one -SkillRuntimeDefaultGate."
    }
    $apiKey = Get-ConfiguredApiKey
    if (-not $HarnessSmoke -and [string]::IsNullOrWhiteSpace($apiKey)) {
        throw "M2 runtime requires SINGULARITY_LLM_API_KEY or OPENAI_API_KEY."
    }
    if (-not [string]::IsNullOrWhiteSpace($apiKey)) {
        $env:SINGULARITY_LLM_API_KEY = $apiKey
    }

    New-Item -ItemType Directory -Force -Path $runtimeLogRoot | Out-Null
    $resultParent = Split-Path -Parent $benchmarkPath
    if ($resultParent) { New-Item -ItemType Directory -Force -Path $resultParent | Out-Null }
    foreach ($path in @($preflightPath, $manifestPath, $blockerPath, $benchmarkPath)) {
        if (Test-Path -LiteralPath $path) {
            throw "M2 runtime refuses to overwrite evidence at $path."
        }
    }
    Assert-File $jarPath "M2 runtime blocked: server jar missing at $jarPath."
    Assert-File $eulaPath "M2 runtime blocked: eula.txt is missing."
    Assert-File $propertiesPath "M2 runtime blocked: server.properties is missing."
    Assert-File $protocolPath "M2 runtime blocked: m2_protocol.json is missing."
    if (-not (Select-String -LiteralPath $eulaPath -Pattern '^\s*eula\s*=\s*true\s*$' -Quiet)) {
        throw "M2 runtime blocked: eula=true is not present. This script never edits eula.txt."
    }

    $protocol = Get-Content -LiteralPath $protocolPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $HarnessSmoke) {
        $env:SINGULARITY_LLM_BASE_URL = [string]$protocol.llm.base_url
    }
    $serverJarSha256 = (Get-FileHash -LiteralPath $jarPath -Algorithm SHA256).Hash.ToLower()
    $protocolSha256 = (Get-FileHash -LiteralPath $protocolPath -Algorithm SHA256).Hash.ToLower()
    if ($serverJarSha256 -ne [string]$protocol.server_jar_sha256) {
        throw "M2 runtime blocked: server jar SHA-256 does not match $($protocol.server_build)."
    }
    if ((Get-ServerProperty $propertiesPath "level-seed") -ne [string]$protocol.world_seed) {
        throw "M2 runtime blocked: server.properties must use level-seed=$($protocol.world_seed)."
    }
    if ((Get-ServerProperty $propertiesPath "online-mode") -ne "false") {
        throw "M2 runtime blocked: server.properties must use online-mode=false."
    }
    $configuredPort = Get-ServerProperty $propertiesPath "server-port"
    if ($configuredPort -and [int]$configuredPort -ne $MinecraftPort) {
        throw "M2 runtime blocked: server.properties uses port $configuredPort, requested $MinecraftPort."
    }
    $opsPath = Join-Path $serverRoot "ops.json"
    Assert-File $opsPath "M2 runtime blocked: ops.json is missing."
    $operators = @(Get-Content -LiteralPath $opsPath -Raw -Encoding UTF8 | ConvertFrom-Json)
    if (-not ($operators | Where-Object { $_.name -eq $Username })) {
        throw "M2 runtime blocked: $Username is not an operator."
    }

    foreach ($suffix in @("", "_nether", "_the_end")) {
        $worldPath = Join-Path $serverRoot ($levelName + $suffix)
        if (Test-Path -LiteralPath $worldPath) {
            throw "M2 runtime blocked: fresh episode world already exists at $worldPath."
        }
    }
    if (Test-TcpEndpoint $MinecraftHost $MinecraftPort) {
        throw "M2 runtime blocked: Minecraft endpoint is already occupied."
    }
    if (Test-TcpEndpoint "127.0.0.1" $BridgePort) {
        throw "M2 runtime blocked: bridge port $BridgePort is already occupied."
    }

    $originalServerProperties = [System.IO.File]::ReadAllText($propertiesPath)
    $updated = Set-ServerPropertyValue $originalServerProperties "level-name" $levelName
    [System.IO.File]::WriteAllText($propertiesPath, $updated, [System.Text.UTF8Encoding]::new($false))
    $serverPropertiesModified = $true

    $serverStdout = Join-Path $runtimeLogRoot "m2_server_$artifactLabel.stdout.log"
    $serverStderr = Join-Path $runtimeLogRoot "m2_server_$artifactLabel.stderr.log"
    $serverProcess = Start-Process -FilePath "java" -ArgumentList @("-Xms1G", "-Xmx2G", "-jar", $ServerJar, "nogui") -WorkingDirectory $serverRoot -RedirectStandardOutput $serverStdout -RedirectStandardError $serverStderr -WindowStyle Hidden -PassThru
    if (-not (Wait-ForTcpEndpoint $MinecraftHost $MinecraftPort $ServerWaitSeconds)) {
        throw "M2 runtime blocked: Minecraft did not become ready. Inspect $serverStdout and $serverStderr."
    }

    $bridgeStdout = Join-Path $runtimeLogRoot "m2_bridge_$artifactLabel.stdout.log"
    $bridgeStderr = Join-Path $runtimeLogRoot "m2_bridge_$artifactLabel.stderr.log"
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
    $health = Wait-ForBridgeSession "127.0.0.1" $BridgePort $BridgeWaitSeconds
    if (-not $health) {
        throw "M2 runtime blocked: bridge did not report bot_ready=true. Inspect $bridgeStdout and $bridgeStderr."
    }

    $manifest = [ordered]@{
        type = if ($HarnessSmoke) { "m2_harness_runtime_manifest" } else { "m2_runtime_manifest" }
        schema_version = 1
        generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        evidence_kind = if ($HarnessSmoke) { "live_minecraft_harness_setup" } else { "runtime_setup" }
        counts_toward_live_observed = $false
        counts_toward_repeat_verified = $false
        episode_id = $episodeId
        task_id = $TaskId
        arm = $modeLabel
        pair_id = $PairId
        replicate_id = $ReplicateId
        protocol_profile = [string]$protocol.profile
        protocol_sha256 = $protocolSha256
        reset_protocol_sha256 = [string]$protocol.reset_protocol_sha256
        validation_protocol_sha256 = [string]$protocol.validation_protocol_sha256
        server_jar_sha256 = $serverJarSha256
        world_seed = [string]$protocol.world_seed
        level_name = $levelName
        planner_id = [string]$protocol.planner_id
        action_backend_id = [string]$protocol.action_backend_id
        verifier_id = [string]$protocol.verifier_id
        skill_runtime_profile_id = [string]$protocol.skill_runtime_profile_id
        llm_provider = [string]$protocol.llm.provider
        llm_base_url = [string]$protocol.llm.base_url
        llm_model = [string]$protocol.llm.model
        llm_temperature = [double]$protocol.llm.temperature
        llm_max_tokens = [int]$protocol.llm.max_tokens
        skill_id = $SkillId
        experiment_id = $ExperimentId
    }
    [System.IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 6), [System.Text.UTF8Encoding]::new($false))

    $preflightMode = if ($HarnessSmoke) { "--m2-harness-only" } else { "--m2" }
    & python -m singularity.main preflight $preflightMode --host $MinecraftHost --port $MinecraftPort --username $Username --bridge-host 127.0.0.1 --bridge-port $BridgePort --output $preflightPath
    if ($LASTEXITCODE -ne 0) { throw "M2 preflight failed; inspect $preflightPath." }

    if ($HarnessSmoke) {
        $smokeArgs = @(
            "-m", "singularity.main", "m2-harness-smoke",
            "--task-id", $TaskId,
            "--host", $MinecraftHost,
            "--port", $MinecraftPort,
            "--username", $Username,
            "--bridge-host", "127.0.0.1",
            "--bridge-port", $BridgePort,
            "--output", $benchmarkPath
        )
        if ($TemplateSmoke) { $smokeArgs += "--execute-template" }
        & python @smokeArgs
        if ($LASTEXITCODE -ne 0) { throw "M2 harness smoke failed; inspect $benchmarkPath." }
        Assert-File $benchmarkPath "M2 harness smoke did not write its report."
        $smoke = Get-Content -LiteralPath $benchmarkPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($smoke.ok -ne $true) { throw "M2 harness smoke report is not approved." }
        Write-Host "M2 harness smoke passed: $TaskId"
    }
    else {
        $benchmarkArgs = @(
            "-m", "singularity.main", "benchmark",
            "--suite", "m2",
            "--task-id", $TaskId,
            "--preflight",
            "--host", $MinecraftHost,
            "--port", $MinecraftPort,
            "--username", $Username,
            "--bridge-host", "127.0.0.1",
            "--bridge-port", $BridgePort,
            "--skill-storage-path", $SkillStoragePath,
            "--m2-arm", $Arm,
            "--output", $benchmarkPath
        )
        if ($PairId) { $benchmarkArgs += @("--m2-pair-id", $PairId) }
        if ($ReplicateId) { $benchmarkArgs += @("--m2-replicate-id", $ReplicateId) }
        if ($Arm -eq "candidate") {
            $benchmarkArgs += @(
                "--skill-execution-mode", "runtime",
                "--target-skill-id", $SkillId,
                "--skill-experiment-id", $ExperimentId
            )
            foreach ($gate in $SkillRuntimeDefaultGate) {
                $benchmarkArgs += @("--skill-runtime-default-gate", $gate)
            }
        }
        & python @benchmarkArgs
        if ($LASTEXITCODE -ne 0) { throw "M2 benchmark command failed; inspect $benchmarkPath." }
        Assert-File $benchmarkPath "M2 benchmark did not write its result."
        $results = @(Get-Content -LiteralPath $benchmarkPath -Raw -Encoding UTF8 | ConvertFrom-Json)
        if ($results.Count -ne 1) { throw "M2 benchmark must contain exactly one result." }
        $result = $results[0]
        if ($result.status -ne "pass" -or $result.protocol_eligible -ne $true) {
            throw "M2 benchmark failed eligibility: status=$($result.status), protocol_eligible=$($result.protocol_eligible), reason=$($result.failure_reason)."
        }
        Write-Host "M2 benchmark passed: $TaskId ($($result.session_id))"
    }

    Write-Host "Evidence: $benchmarkPath"
    Write-Host "Manifest: $manifestPath"
    if ($KeepProcesses) {
        Write-Host "Minecraft PID: $($serverProcess.Id); bridge PID: $($bridgeProcess.Id)"
        $serverProcess = $null
        $bridgeProcess = $null
    }
}
catch {
    $message = [string]$_.Exception.Message
    $blocker = [ordered]@{
        type = if ($HarnessSmoke) { "m2_harness_runtime_blocker" } else { "m2_runtime_blocker" }
        schema_version = 1
        generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        evidence_kind = "runtime_setup_or_live_failure"
        counts_toward_live_observed = $false
        counts_toward_repeat_verified = $false
        task_id = $TaskId
        arm = $modeLabel
        pair_id = $PairId
        replicate_id = $ReplicateId
        blocker = $message
        benchmark_result_path = $benchmarkPath.Replace($repoRoot + [System.IO.Path]::DirectorySeparatorChar, "")
        manifest_path = $manifestPath.Replace($repoRoot + [System.IO.Path]::DirectorySeparatorChar, "")
        eula_accepted = [bool](Test-Path -LiteralPath $eulaPath -PathType Leaf) -and [bool](Select-String -LiteralPath $eulaPath -Pattern '^\s*eula\s*=\s*true\s*$' -Quiet)
        api_key_configured = -not [string]::IsNullOrWhiteSpace((Get-ConfiguredApiKey))
    }
    if (-not (Test-Path -LiteralPath $blockerPath)) {
        [System.IO.File]::WriteAllText($blockerPath, ($blocker | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
        Write-Host "Blocker evidence: $blockerPath"
    }
    throw
}
finally {
    Stop-OwnedProcess $bridgeProcess
    Stop-OwnedProcess $serverProcess
    if ($serverPropertiesModified -and $null -ne $originalServerProperties) {
        [System.IO.File]::WriteAllText($propertiesPath, $originalServerProperties, [System.Text.UTF8Encoding]::new($false))
    }
    Pop-Location
}

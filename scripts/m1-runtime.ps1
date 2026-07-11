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
    [ValidateSet("", "BM-001", "BM-002", "BM-003", "BM-004", "BM-005")]
    [string]$TaskId = "",
    [switch]$RunBenchmark,
    [ValidateSet("", "baseline", "shadow", "advisory", "candidate", "runtime", "fallback", "fault", "extraction")]
    [string]$SkillLearningArm = "",
    [string]$SkillId = "",
    [string]$ExperimentId = "",
    [string]$PairId = "",
    [string]$ReplicateId = "",
    [string]$ResearchGoal = "",
    [string]$SuccessCriteriaJson = "",
    [string]$SuccessCriteriaFile = "",
    [ValidateSet("protocol_default", "gather_oak_near_v1", "gather_oak_shifted_v1", "wooden_pickaxe_table_shift_v1")]
    [string]$ResearchFixtureProfile = "protocol_default",
    [string]$SkillStoragePath = "workspace/skills",
    [string]$SkillLedgerPath = "workspace/evals/skill_learning_ledger.json",
    [string]$SkillRegressionsPath = "workspace/evals/skill_regressions.json",
    [string[]]$SkillRuntimeDefaultGate = @(),
    [ValidateSet("", "reject_skill_craft_missing_item_v1", "reject_skill_place_missing_item_v1", "reject_skill_equip_missing_item_v1")]
    [string]$SkillFaultProfile = "",
    [string]$SkillOutputPath = "",
    [switch]$Heldout,
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
$researchRun = -not [string]::IsNullOrWhiteSpace($SkillLearningArm)
$episodeId = if ($researchRun) { "skill_episode_$timestamp" } else { "m1_episode_$timestamp" }
$runtimeLogRoot = Join-Path $repoRoot "logs\benchmarks\runtime"
$artifactPrefix = if ($researchRun) { "skill_learning" } else { "m1" }
$preflightPath = Join-Path $repoRoot "logs\benchmarks\${artifactPrefix}_preflight_$timestamp.json"
$manifestPath = Join-Path $repoRoot "logs\benchmarks\${artifactPrefix}_runtime_manifest_$timestamp.json"
$defaultBenchmarkPath = if ($researchRun) {
    Join-Path $repoRoot "workspace\evals\skill_ablation\runs\skill_run_${timestamp}_${SkillLearningArm}_${TaskId}.json"
} else {
    Join-Path $repoRoot "logs\benchmarks\m1_benchmark_$timestamp.json"
}
$benchmarkPath = if ($SkillOutputPath) {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $SkillOutputPath))
} else {
    $defaultBenchmarkPath
}
$blockerPath = Join-Path $repoRoot "logs\benchmarks\${artifactPrefix}_runtime_blocker_$timestamp.json"
$serverProcess = $null
$bridgeProcess = $null
$originalServerProperties = $null
$serverPropertiesModified = $false

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

function Set-ServerPropertyValue {
    param([string]$Content, [string]$Name, [string]$Value)

    $pattern = "(?m)^\s*$([regex]::Escape($Name))\s*=.*$"
    $replacement = "$Name=$Value"
    if ([regex]::IsMatch($Content, $pattern)) {
        return [regex]::Replace($Content, $pattern, $replacement)
    }
    return $Content.TrimEnd() + [Environment]::NewLine + $replacement + [Environment]::NewLine
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
    param([string]$HostName, [int]$Port, [int]$TimeoutSeconds, [switch]$RequireBenchmark)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $health = Get-BridgeHealth -HostName $HostName -Port $Port
        $benchmarkReady = -not $RequireBenchmark
        if ($health -and $RequireBenchmark) {
            $benchmarkReady = $health.benchmark_protocol.configured -eq $true
        }
        if ($health -and $health.success -eq $true -and $health.bridge -eq $true -and $health.bot_ready -eq $true -and $benchmarkReady) {
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
    $benchmarkParent = Split-Path -Parent $benchmarkPath
    if ($benchmarkParent) {
        New-Item -ItemType Directory -Force -Path $benchmarkParent | Out-Null
    }
    foreach ($evidencePath in @($preflightPath, $manifestPath, $benchmarkPath, $blockerPath)) {
        if (Test-Path -LiteralPath $evidencePath) {
            throw "M1 runtime blocked: refusing to overwrite evidence at $evidencePath."
        }
    }
    Assert-File -Path $jarPath -Message "M1 runtime blocked: $jarPath is missing. Place a Minecraft 1.20.4 Paper server jar there."
    Assert-File -Path $eulaPath -Message "M1 runtime blocked: $eulaPath is missing. Start the server once, read the Minecraft EULA, and edit eula.txt manually. This script never accepts the EULA."
    if (-not (Select-String -LiteralPath $eulaPath -Pattern '^\s*eula\s*=\s*true\s*$' -Quiet)) {
        throw "M1 runtime blocked: eula=true is not present in $eulaPath. Read and accept the Minecraft EULA manually; this script never edits eula.txt."
    }
    Assert-File -Path $propertiesPath -Message "M1 runtime blocked: $propertiesPath is missing. Generate it with the server, then configure the fixed M1 protocol."
    if ($RunBenchmark -and -not $TaskId) {
        throw "M1 runtime blocked: -RunBenchmark requires exactly one -TaskId so each task receives a fresh world episode."
    }
    if ($TaskId -and -not $RunBenchmark) {
        throw "M1 runtime blocked: -TaskId is only valid with -RunBenchmark."
    }
    if ($researchRun -and -not $RunBenchmark) {
        throw "Skill-learning runtime blocked: -SkillLearningArm requires -RunBenchmark."
    }
    if ($researchRun -and (-not $SkillId -or -not $ExperimentId)) {
        throw "Skill-learning runtime blocked: -SkillId and -ExperimentId are required for every research arm."
    }
    if (-not $researchRun -and ($SkillId -or $ExperimentId -or $SkillOutputPath)) {
        throw "M1 runtime blocked: skill-learning arguments require -SkillLearningArm."
    }
    if ($SkillLearningArm -eq "runtime" -and $SkillRuntimeDefaultGate.Count -lt 1) {
        throw "Skill-learning runtime blocked: runtime arm requires -SkillRuntimeDefaultGate."
    }
    if ($SkillLearningArm -eq "fault" -and -not $SkillFaultProfile) {
        throw "Skill-learning runtime blocked: fault arm requires -SkillFaultProfile."
    }
    if ($SkillLearningArm -ne "fault" -and $SkillFaultProfile) {
        throw "Skill-learning runtime blocked: -SkillFaultProfile is only valid with the fault arm."
    }
    if ($SuccessCriteriaJson -and $SuccessCriteriaFile) {
        throw "Skill-learning runtime blocked: use only one of -SuccessCriteriaJson or -SuccessCriteriaFile."
    }
    $resolvedSuccessCriteriaFile = ""
    if ($SuccessCriteriaFile) {
        $resolvedSuccessCriteriaFile = if ([System.IO.Path]::IsPathRooted($SuccessCriteriaFile)) {
            [System.IO.Path]::GetFullPath($SuccessCriteriaFile)
        }
        else {
            [System.IO.Path]::GetFullPath((Join-Path $repoRoot $SuccessCriteriaFile))
        }
        Assert-File -Path $resolvedSuccessCriteriaFile -Message "Skill-learning runtime blocked: success-criteria file is missing: $resolvedSuccessCriteriaFile"
    }

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
    $serverJarSha256 = (Get-FileHash -LiteralPath $jarPath -Algorithm SHA256).Hash.ToLower()
    $protocolPath = Join-Path $repoRoot "src\singularity\data\m1_protocol.json"
    $protocolSha256 = (Get-FileHash -LiteralPath $protocolPath -Algorithm SHA256).Hash.ToLower()
    $protocol = Get-Content -LiteralPath $protocolPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($serverJarSha256 -ne [string]$protocol.server_jar_sha256) {
        throw "M1 runtime blocked: server.jar SHA-256 does not match pinned $($protocol.server_build)."
    }

    if ($RunBenchmark) {
        $opsPath = Join-Path $serverRoot "ops.json"
        Assert-File -Path $opsPath -Message "M1 runtime blocked: $opsPath is missing. Start the controlled server, run 'op $Username' in its console, then stop it."
        try {
            $operators = @(Get-Content -LiteralPath $opsPath -Raw | ConvertFrom-Json)
        }
        catch {
            throw "M1 runtime blocked: $opsPath is not valid JSON."
        }
        if (-not ($operators | Where-Object { $_.name -eq $Username })) {
            throw "M1 runtime blocked: $Username is not listed in ops.json. Run 'op $Username' in the controlled server console."
        }

    }
    $runLabel = if ($TaskId) { $TaskId.ToLower().Replace("-", "_") } else { "preflight" }
    $levelName = "${episodeId}_${runLabel}"
    foreach ($suffix in @("", "_nether", "_the_end")) {
        $worldPath = Join-Path $serverRoot ($levelName + $suffix)
        if (Test-Path -LiteralPath $worldPath) {
            throw "M1 runtime blocked: fresh episode world already exists at $worldPath."
        }
    }
    $originalServerProperties = [System.IO.File]::ReadAllText($propertiesPath)
    $updatedProperties = Set-ServerPropertyValue -Content $originalServerProperties -Name "level-name" -Value $levelName
    [System.IO.File]::WriteAllText(
        $propertiesPath,
        $updatedProperties,
        [System.Text.UTF8Encoding]::new($false)
    )
    $serverPropertiesModified = $true
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
        "--bridge-port", $BridgePort,
        "--benchmark-seed", "12345",
        "--benchmark-episode", $episodeId,
        "--benchmark-level-name", $levelName,
        "--benchmark-server-jar-sha256", $serverJarSha256
    )
    $bridgeProcess = Start-Process -FilePath "node" -ArgumentList $bridgeArguments -WorkingDirectory $repoRoot -RedirectStandardOutput $bridgeStdout -RedirectStandardError $bridgeStderr -WindowStyle Hidden -PassThru
    $health = Wait-ForBridgeSession -HostName "127.0.0.1" -Port $BridgePort -TimeoutSeconds $BridgeWaitSeconds -RequireBenchmark
    if (-not $health) {
        throw "M1 runtime blocked: the Singularity bridge did not report bot_ready=true within $BridgeWaitSeconds seconds. Inspect $bridgeStdout and $bridgeStderr."
    }
    if ([string]$health.version -ne "1.20.4") {
        throw "M1 runtime blocked: the spawned bot reports Minecraft version '$($health.version)', expected 1.20.4."
    }

    $manifest = [ordered]@{
        type = if ($researchRun) { "skill_learning_runtime_manifest" } else { "m1_runtime_manifest" }
        schema_version = 1
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        evidence_kind = "runtime_setup"
        counts_toward_live_observed = $false
        counts_toward_repeat_verified = $false
        episode_id = $episodeId
        task_id = $TaskId
        minecraft_version = "1.20.4"
        server_type = "Paper"
        server_build = [string]$protocol.server_build
        server_brand = [string]$health.server_brand
        server_jar_sha256 = $serverJarSha256
        protocol_sha256 = $protocolSha256
        protocol_profile = [string]$protocol.profile
        server_jar_policy = [string]$protocol.server_jar_policy
        agent_id = [string]$protocol.agent_id
        planner_id = [string]$protocol.planner_id
        action_backend_id = [string]$protocol.action_backend_id
        verifier_id = [string]$protocol.verifier_id
        world_seed = "12345"
        level_name = $levelName
        minecraft_endpoint = "$MinecraftHost`:$MinecraftPort"
        bridge_endpoint = "127.0.0.1`:$BridgePort"
        username = $Username
        run_benchmark = [bool]$RunBenchmark
        skill_learning_arm = $SkillLearningArm
        skill_id = $SkillId
        experiment_id = $ExperimentId
        pair_id = $PairId
        replicate_id = $ReplicateId
        heldout = [bool]$Heldout
        research_fixture_profile = $ResearchFixtureProfile
        counts_toward_m1_acceptance = -not $researchRun
    }
    [System.IO.File]::WriteAllText(
        $manifestPath,
        ($manifest | ConvertTo-Json -Depth 5),
        [System.Text.UTF8Encoding]::new($false)
    )

    & python -m singularity.main preflight --m1 --host $MinecraftHost --port $MinecraftPort --username $Username --bridge-host 127.0.0.1 --bridge-port $BridgePort --output $preflightPath
    if ($LASTEXITCODE -ne 0) {
        throw "M1 runtime preflight failed. Evidence: $preflightPath"
    }

    Write-Host "M1 runtime preflight passed."
    Write-Host "Evidence: $preflightPath"
    Write-Host "Manifest: $manifestPath"
    if ($RunBenchmark) {
        if ($researchRun) {
            $benchmarkArguments = @(
                "-m", "singularity.main", "skill-learning-run",
                "--task-id", $TaskId,
                "--arm", $SkillLearningArm,
                "--skill-id", $SkillId,
                "--experiment-id", $ExperimentId,
                "--research-fixture-profile", $ResearchFixtureProfile,
                "--skill-storage-path", $SkillStoragePath,
                "--ledger", $SkillLedgerPath,
                "--regressions", $SkillRegressionsPath,
                "--host", $MinecraftHost,
                "--port", $MinecraftPort,
                "--username", $Username,
                "--bridge-host", "127.0.0.1",
                "--bridge-port", $BridgePort,
                "--output", $benchmarkPath
            )
            if ($PairId) { $benchmarkArguments += @("--pair-id", $PairId) }
            if ($ReplicateId) { $benchmarkArguments += @("--replicate-id", $ReplicateId) }
            if ($ResearchGoal) { $benchmarkArguments += @("--goal", $ResearchGoal) }
            if ($SuccessCriteriaJson) { $benchmarkArguments += @("--success-criteria-json", $SuccessCriteriaJson) }
            if ($resolvedSuccessCriteriaFile) { $benchmarkArguments += @("--success-criteria-file", $resolvedSuccessCriteriaFile) }
            if ($Heldout) { $benchmarkArguments += "--heldout" }
            foreach ($gatePath in $SkillRuntimeDefaultGate) {
                $benchmarkArguments += @("--skill-runtime-default-gate", $gatePath)
            }
            if ($SkillFaultProfile) { $benchmarkArguments += @("--skill-fault-profile", $SkillFaultProfile) }
        }
        else {
            $benchmarkArguments = @(
                "-m", "singularity.main", "benchmark",
                "--suite", "m1",
                "--task-id", $TaskId,
                "--preflight",
                "--host", $MinecraftHost,
                "--port", $MinecraftPort,
                "--username", $Username,
                "--bridge-host", "127.0.0.1",
                "--bridge-port", $BridgePort,
                "--output", $benchmarkPath
            )
        }
        & python @benchmarkArguments
        if ($LASTEXITCODE -ne 0) {
            throw "Controlled benchmark command failed. Inspect $benchmarkPath and runtime logs."
        }
        Write-Host "Benchmark evidence: $benchmarkPath"
    }
    else {
        Write-Host "Next command: powershell -ExecutionPolicy Bypass -File scripts/m1-runtime.ps1 -RunBenchmark -TaskId BM-001"
    }
    if ($KeepProcesses) {
        Write-Host "Minecraft PID: $($serverProcess.Id); bridge PID: $($bridgeProcess.Id)"
        $serverProcess = $null
        $bridgeProcess = $null
    }
}
catch {
    $message = [string]$_.Exception.Message
    $jarHash = ""
    if (Test-Path -LiteralPath $jarPath -PathType Leaf) {
        $jarHash = (Get-FileHash -LiteralPath $jarPath -Algorithm SHA256).Hash.ToLower()
    }
    $protocolHash = ""
    $protocolFile = Join-Path $repoRoot "src\singularity\data\m1_protocol.json"
    if (Test-Path -LiteralPath $protocolFile -PathType Leaf) {
        $protocolHash = (Get-FileHash -LiteralPath $protocolFile -Algorithm SHA256).Hash.ToLower()
    }
    $eulaAccepted = $false
    if (Test-Path -LiteralPath $eulaPath -PathType Leaf) {
        $eulaAccepted = [bool](Select-String -LiteralPath $eulaPath -Pattern '^\s*eula\s*=\s*true\s*$' -Quiet)
    }
    $blocker = [ordered]@{
        type = if ($researchRun) { "skill_learning_runtime_blocker" } else { "m1_runtime_blocker" }
        schema_version = 1
        generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        evidence_kind = "runtime_setup_failure"
        counts_toward_live_observed = $false
        counts_toward_repeat_verified = $false
        task_id = $TaskId
        run_benchmark = [bool]$RunBenchmark
        skill_learning_arm = $SkillLearningArm
        skill_id = $SkillId
        experiment_id = $ExperimentId
        failure_layer = if ($message -match "EULA|eula") { "environment_eula" } else { "environment_runtime" }
        blocker = $message
        server_jar_present = [bool](Test-Path -LiteralPath $jarPath -PathType Leaf)
        server_jar_sha256 = $jarHash
        protocol_sha256 = $protocolHash
        eula_present = [bool](Test-Path -LiteralPath $eulaPath -PathType Leaf)
        eula_accepted = $eulaAccepted
        server_properties_present = [bool](Test-Path -LiteralPath $propertiesPath -PathType Leaf)
        ops_present = [bool](Test-Path -LiteralPath (Join-Path $serverRoot "ops.json") -PathType Leaf)
        manual_action_required = [bool]($message -match "EULA|eula")
        next_command = "powershell -ExecutionPolicy Bypass -File scripts/m1-runtime.ps1 -RunBenchmark -TaskId BM-001"
    }
    if (-not (Test-Path -LiteralPath $blockerPath)) {
        [System.IO.File]::WriteAllText(
            $blockerPath,
            ($blocker | ConvertTo-Json -Depth 5),
            [System.Text.UTF8Encoding]::new($false)
        )
        Write-Host "Blocker evidence: $blockerPath"
    }
    throw
}
finally {
    Stop-OwnedProcess -Process $bridgeProcess
    Stop-OwnedProcess -Process $serverProcess
    if ($serverPropertiesModified -and $null -ne $originalServerProperties) {
        [System.IO.File]::WriteAllText(
            $propertiesPath,
            $originalServerProperties,
            [System.Text.UTF8Encoding]::new($false)
        )
    }
    Pop-Location
}

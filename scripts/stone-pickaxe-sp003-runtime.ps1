[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("baseline", "candidate")]
    [string]$Arm,
    [Parameter(Mandatory = $true)]
    [ValidateSet("baseline", "r1", "r2", "r3")]
    [string]$ReplicateId,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9][a-z0-9_-]{0,95}$')]
    [string]$EpisodeId,
    [string]$ServerDirectory = "mc-server",
    [string]$ServerJar = "server.jar",
    [string]$MinecraftHost = "127.0.0.1",
    [int]$MinecraftPort = 25565,
    [string]$Username = "Singularity",
    [int]$BridgePort = 30000,
    [int]$ServerWaitSeconds = 180,
    [int]$BridgeWaitSeconds = 45
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$serverRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $ServerDirectory))
$jarPath = Join-Path $serverRoot $ServerJar
$eulaPath = Join-Path $serverRoot "eula.txt"
$propertiesPath = Join-Path $serverRoot "server.properties"
$opsPath = Join-Path $serverRoot "ops.json"
$protocolPath = Join-Path $repoRoot "workspace\evals\stone_pickaxe_protocol.json"
$policyPath = Join-Path $repoRoot "workspace\evals\stone_pickaxe_sp003_harness_policy.json"
$navigationPreloadPath = Join-Path $repoRoot "src\bot\sp003_inventory_preserving_navigation.js"
$authorizationPath = Join-Path $repoRoot "workspace\evals\stone_pickaxe_sp003_next_authorization.json"
$authorizationRelative = "workspace/evals/stone_pickaxe_sp003_next_authorization.json"
$runtimeLogRoot = Join-Path $repoRoot "logs\stone_pickaxe\sp003_runtime"
$levelName = "${EpisodeId}_world"
$outputRelative = "workspace/evals/sp003_runs/$EpisodeId"
$outputRoot = Join-Path $repoRoot $outputRelative
$serverProcess = $null
$bridgeProcess = $null
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
        if (Test-TcpEndpoint $HostName $Port) { return $true }
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
        $reader = [System.IO.StreamReader]::new(
            $stream,
            [System.Text.Encoding]::UTF8,
            $false,
            1024,
            $true
        )
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
        $health = Get-BridgeHealth $HostName $Port
        if ($health -and $health.success -eq $true -and $health.bot_ready -eq $true) {
            return $health
        }
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

function Assert-CleanSynchronizedMain {
    $branch = (& git branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or $branch -ne "main") {
        throw "SP-003 runtime requires branch main."
    }
    $status = @(& git status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $status.Count -ne 0) {
        throw "SP-003 runtime requires a clean worktree."
    }
    $head = (& git rev-parse HEAD).Trim()
    $origin = (& git rev-parse origin/main).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -ne $origin) {
        throw "SP-003 runtime requires HEAD == origin/main."
    }
    return $head
}

function Get-AuthorizationParent {
    $parents = ((& git rev-list --parents -n 1 HEAD).Trim() -split '\s+')
    if ($LASTEXITCODE -ne 0 -or $parents.Count -ne 2) {
        throw "SP-003 authorization requires one non-merge parent commit."
    }
    $changed = @(
        @(& git diff-tree --no-commit-id --name-only -r HEAD) | ForEach-Object {
            $_.Trim().Replace('\', '/')
        } | Where-Object { $_ }
    )
    if ($LASTEXITCODE -ne 0 -or $changed.Count -ne 1 -or $changed[0] -ne $authorizationRelative) {
        throw "The current commit must contain only the one-time SP-003 authorization."
    }
    return $parents[1]
}

function Assert-FreshRuntimePaths {
    if (Test-Path -LiteralPath $outputRoot) {
        throw "SP-003 evidence directory already exists; reruns are forbidden: $outputRoot"
    }
    foreach ($name in @($levelName, "${levelName}_nether", "${levelName}_the_end")) {
        $path = [System.IO.Path]::GetFullPath((Join-Path $serverRoot $name))
        $serverPrefix = $serverRoot.TrimEnd('\') + '\'
        if (-not $path.StartsWith($serverPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "SP-003 world path escaped the server root."
        }
        if (Test-Path -LiteralPath $path) {
            throw "SP-003 requires a fresh unique world: $path"
        }
    }
}

function Set-EpisodeServerProperties {
    $script:originalServerPropertiesBytes = [System.IO.File]::ReadAllBytes($propertiesPath)
    $content = [System.Text.Encoding]::UTF8.GetString($script:originalServerPropertiesBytes)
    foreach ($entry in ([ordered]@{
        "level-name" = $levelName
        "level-seed" = "12345"
        "server-port" = [string]$MinecraftPort
        "online-mode" = "false"
        "gamemode" = "survival"
        "force-gamemode" = "false"
        "difficulty" = "normal"
        "spawn-monsters" = "true"
    }).GetEnumerator()) {
        $content = Set-ServerPropertyValue $content $entry.Key $entry.Value
    }
    [System.IO.File]::WriteAllText(
        $propertiesPath,
        $content,
        [System.Text.UTF8Encoding]::new($false)
    )
    $script:serverPropertiesModified = $true
}

function Start-ControlledRuntime {
    param([string]$ServerJarSha256)
    New-Item -ItemType Directory -Force -Path $runtimeLogRoot | Out-Null
    $serverStdout = Join-Path $runtimeLogRoot "server_${EpisodeId}.stdout.log"
    $serverStderr = Join-Path $runtimeLogRoot "server_${EpisodeId}.stderr.log"
    $script:serverProcess = Start-Process -FilePath "java" -ArgumentList @(
        "-Xms1G", "-Xmx2G", "-jar", $ServerJar, "nogui"
    ) -WorkingDirectory $serverRoot -RedirectStandardOutput $serverStdout -RedirectStandardError $serverStderr -WindowStyle Hidden -PassThru
    if (-not (Wait-ForTcpEndpoint $MinecraftHost $MinecraftPort $ServerWaitSeconds)) {
        throw "Minecraft did not become ready for $EpisodeId."
    }

    $bridgeStdout = Join-Path $runtimeLogRoot "bridge_${EpisodeId}.stdout.log"
    $bridgeStderr = Join-Path $runtimeLogRoot "bridge_${EpisodeId}.stderr.log"
    $bridgeArgs = @(
        "--require", "./src/bot/sp003_inventory_preserving_navigation.js",
        "src/bot/bot_server.js",
        "--host", $MinecraftHost,
        "--port", $MinecraftPort,
        "--username", $Username,
        "--version", "1.20.4",
        "--bridge-port", $BridgePort,
        "--benchmark-seed", "12345",
        "--benchmark-episode", $EpisodeId,
        "--benchmark-level-name", $levelName,
        "--benchmark-server-jar-sha256", $ServerJarSha256,
        "--craft-max-attempts", "1"
    )
    $script:bridgeProcess = Start-Process -FilePath "node" -ArgumentList $bridgeArgs -WorkingDirectory $repoRoot -RedirectStandardOutput $bridgeStdout -RedirectStandardError $bridgeStderr -WindowStyle Hidden -PassThru
    $health = Wait-ForBridgeSession "127.0.0.1" $BridgePort $BridgeWaitSeconds
    if (-not $health) {
        throw "Bridge did not report bot_ready=true for $EpisodeId."
    }
    if (-not $health.craft_policy -or [int]$health.craft_policy.max_attempts -ne 1) {
        throw "SP-003 bridge did not prove craft max_attempts=1."
    }
    if ($health.craft_policy.automatic_retry -ne $false) {
        throw "SP-003 bridge must disable craft automatic retry."
    }
}

function Stop-ControlledRuntime {
    Stop-OwnedProcess $script:bridgeProcess
    $script:bridgeProcess = $null
    Start-Sleep -Seconds 2
    Stop-OwnedProcess $script:serverProcess
    $script:serverProcess = $null
}

Push-Location $repoRoot
try {
    if (($Arm -eq "baseline") -ne ($ReplicateId -eq "baseline")) {
        throw "Arm/ReplicateId must be baseline/baseline or candidate/r1..r3."
    }
    Assert-File $jarPath "Pinned Paper server jar is missing at $jarPath."
    Assert-File $eulaPath "eula.txt is missing."
    Assert-File $propertiesPath "server.properties is missing."
    Assert-File $opsPath "ops.json is missing."
    Assert-File $protocolPath "Frozen stone-pickaxe protocol is missing."
    Assert-File $policyPath "SP-003 harness policy is missing."
    Assert-File $navigationPreloadPath "SP-003 inventory-preserving navigation preload is missing."
    Assert-File $authorizationPath "The one-time SP-003 authorization is missing."
    if (-not (Select-String -LiteralPath $eulaPath -Pattern '^\s*eula\s*=\s*true\s*$' -Quiet)) {
        throw "SP-003 runtime requires eula=true."
    }
    if ((Get-ServerProperty $propertiesPath "level-seed") -ne "12345") {
        throw "server.properties must contain level-seed=12345 before runtime."
    }
    if ((Get-ServerProperty $propertiesPath "online-mode") -ne "false") {
        throw "server.properties must contain online-mode=false."
    }
    $operators = @(Get-Content -LiteralPath $opsPath -Raw -Encoding UTF8 | ConvertFrom-Json)
    if (-not ($operators | Where-Object { $_.name -eq $Username })) {
        throw "$Username must be an operator for the audited reset."
    }
    if (Test-TcpEndpoint $MinecraftHost $MinecraftPort) {
        throw "Minecraft port $MinecraftPort is already occupied."
    }
    if (Test-TcpEndpoint "127.0.0.1" $BridgePort) {
        throw "Bridge port $BridgePort is already occupied."
    }
    Assert-FreshRuntimePaths

    $gitHead = Assert-CleanSynchronizedMain
    $gitParent = Get-AuthorizationParent
    $authorization = Get-Content -LiteralPath $authorizationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$authorization.episode_id -cne $EpisodeId -or
        [string]$authorization.arm -cne $Arm -or
        [string]$authorization.replicate_id -cne $ReplicateId) {
        throw "Launcher arguments do not match the pushed one-time authorization."
    }
    $protocol = Get-Content -LiteralPath $protocolPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $policy = Get-Content -LiteralPath $policyPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $protocolSha256 = (Get-FileHash -LiteralPath $protocolPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($protocolSha256 -ne [string]$policy.protocol.sha256) {
        throw "Frozen protocol SHA-256 does not match the SP-003 policy."
    }
    $jarSha256 = (Get-FileHash -LiteralPath $jarPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($jarSha256 -ne [string]$protocol.environment.server_jar_sha256 -or
        $jarSha256 -ne [string]$policy.environment.server_jar_sha256) {
        throw "Pinned Paper jar SHA-256 does not match the protocol and policy."
    }
    if ($policy.current_state.offline_harness_ready -ne $true) {
        throw "SP-003 policy does not mark the offline harness ready."
    }
    $apiKey = Get-ConfiguredApiKey
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        throw "SP-003 runtime requires an LLM credential."
    }
    $env:SINGULARITY_LLM_API_KEY = $apiKey
    $env:SINGULARITY_LLM_BASE_URL = [string]$protocol.planner.base_url
    $env:PYTHONPATH = Join-Path $repoRoot "src"

    & python scripts/stone_pickaxe_sp003_episode_runner.py audit-authorization --arm $Arm --replicate-id $ReplicateId --episode-id $EpisodeId --git-head $gitHead --git-parent $gitParent --authorization $authorizationRelative
    if ($LASTEXITCODE -ne 0) { throw "SP-003 authorization audit failed." }

    Set-EpisodeServerProperties
    Start-ControlledRuntime $jarSha256
    & python scripts/stone_pickaxe_sp003_episode_runner.py run --arm $Arm --replicate-id $ReplicateId --episode-id $EpisodeId --level-name $levelName --output-dir $outputRelative --authorization $authorizationRelative --git-head $gitHead --git-parent $gitParent --host $MinecraftHost --port $MinecraftPort --username $Username --bridge-host 127.0.0.1 --bridge-port $BridgePort --fresh-level
    $runnerExit = $LASTEXITCODE
    Stop-ControlledRuntime
    if ($runnerExit -ne 0) {
        throw "The single authorized SP-003 episode failed; automatic retry is forbidden."
    }
    Write-Host "Single SP-003 episode retained: $outputRelative"
    Write-Host "No retry or BM-012 terminal episode was started."
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
    foreach ($entry in ([ordered]@{
        "SINGULARITY_LLM_API_KEY" = $originalApiKey
        "SINGULARITY_LLM_BASE_URL" = $originalBaseUrl
        "PYTHONPATH" = $originalPythonPath
    }).GetEnumerator()) {
        try { [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process") }
        catch { $cleanupErrors.Add([string]$_.Exception.Message) }
    }
    try { Pop-Location }
    catch { $cleanupErrors.Add([string]$_.Exception.Message) }
    if ($cleanupErrors.Count -gt 0) {
        Write-Warning ("SP-003 runtime cleanup issues: " + ($cleanupErrors -join "; "))
    }
}

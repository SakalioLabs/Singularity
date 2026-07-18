[CmdletBinding()]
param(
    [ValidateSet("PrepareSP002Fixture", "RunSP002", "AuditSP002Fixture")]
    [string]$Mode = "AuditSP002Fixture",
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
$protocolPath = Join-Path $repoRoot "workspace\evals\stone_pickaxe_protocol.json"
$policyPath = Join-Path $repoRoot "workspace\evals\stone_pickaxe_sp002_harness_policy.json"
$sourceFixturePath = Join-Path $repoRoot "workspace\evals\stone_pickaxe_fixture.json"
$fixtureManifestPath = Join-Path $repoRoot "workspace\evals\stone_pickaxe_sp002_fixture.json"
$authorizationPath = Join-Path $repoRoot "workspace\evals\stone_pickaxe_sp002_next_authorization.json"
$authorizationRelative = "workspace\evals\stone_pickaxe_sp002_next_authorization.json"
$runtimeLogRoot = Join-Path $repoRoot "logs\stone_pickaxe\sp002_runtime"
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
        throw "SP-002 runtime requires branch main."
    }
    $status = @(& git status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $status.Count -ne 0) {
        throw "SP-002 runtime requires a clean worktree before authorization is consumed."
    }
    $head = (& git rev-parse HEAD).Trim()
    $origin = (& git rev-parse origin/main).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -ne $origin) {
        throw "SP-002 runtime requires HEAD == origin/main."
    }
    return $head
}

function Get-AuthorizationParent {
    $parents = ((& git rev-list --parents -n 1 HEAD).Trim() -split '\s+')
    if ($LASTEXITCODE -ne 0 -or $parents.Count -ne 2) {
        throw "SP-002 authorization requires one non-merge parent commit."
    }
    $changed = @(
        @(& git diff-tree --no-commit-id --name-only -r HEAD) | ForEach-Object {
            $_.Trim().Replace('\', '/')
        } | Where-Object { $_ }
    )
    if ($LASTEXITCODE -ne 0 -or $changed.Count -ne 1 -or $changed[0] -ne $authorizationRelative.Replace('\', '/')) {
        throw "The current commit must contain only the one-time SP-002 authorization."
    }
    return $parents[1]
}

function Assert-PathWithin {
    param([string]$Path, [string]$Parent, [string]$Message)
    $resolvedPath = [System.IO.Path]::GetFullPath($Path)
    $resolvedParent = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    if (-not $resolvedPath.StartsWith($resolvedParent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw $Message
    }
    return $resolvedPath
}

function Get-RepositoryRelativePath {
    param([string]$Path)
    $resolvedPath = [System.IO.Path]::GetFullPath($Path)
    $resolvedRoot = [System.IO.Path]::GetFullPath($repoRoot).TrimEnd('\') + '\'
    if (-not $resolvedPath.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escaped the repository root: $resolvedPath"
    }
    return $resolvedPath.Substring($resolvedRoot.Length)
}

function Resolve-FixtureSnapshot {
    param($Fixture)
    $controlledRoot = Join-Path $repoRoot "logs\stone_pickaxe\fixtures"
    return Assert-PathWithin (Join-Path $repoRoot ([string]$Fixture.snapshot.path)) $controlledRoot "Fixture snapshot path escaped its controlled root."
}

function Copy-SnapshotToLevel {
    param([string]$SnapshotRoot, [string]$LevelName)
    $sourceNames = @("world", "world_nether", "world_the_end")
    $targetNames = @($LevelName, "${LevelName}_nether", "${LevelName}_the_end")
    for ($index = 0; $index -lt $sourceNames.Count; $index++) {
        $source = Assert-PathWithin (Join-Path $SnapshotRoot $sourceNames[$index]) $SnapshotRoot "Restoration source escaped the snapshot root."
        $target = Assert-PathWithin (Join-Path $serverRoot $targetNames[$index]) $serverRoot "Restoration target escaped the server root."
        if (-not (Test-Path -LiteralPath $source -PathType Container)) {
            throw "Snapshot component is missing: $source"
        }
        if (Test-Path -LiteralPath $target) {
            throw "Fresh SP-002 world already exists: $target"
        }
        Copy-Item -LiteralPath $source -Destination $target -Recurse
    }
}

function Copy-LevelToSnapshot {
    param([string]$LevelName, [string]$SnapshotRoot)
    New-Item -ItemType Directory -Path $SnapshotRoot | Out-Null
    $sourceNames = @($LevelName, "${LevelName}_nether", "${LevelName}_the_end")
    $targetNames = @("world", "world_nether", "world_the_end")
    for ($index = 0; $index -lt $sourceNames.Count; $index++) {
        $source = Assert-PathWithin (Join-Path $serverRoot $sourceNames[$index]) $serverRoot "Snapshot source escaped the server root."
        $target = Assert-PathWithin (Join-Path $SnapshotRoot $targetNames[$index]) $SnapshotRoot "Snapshot target escaped the snapshot root."
        if (-not (Test-Path -LiteralPath $source -PathType Container)) {
            throw "Expected saved world component is missing: $source"
        }
        if (Test-Path -LiteralPath $target) {
            throw "Snapshot target already exists: $target"
        }
        Copy-Item -LiteralPath $source -Destination $target -Recurse
    }
}

function Set-EpisodeServerProperties {
    param([string]$LevelName, [string]$Seed)
    $script:originalServerPropertiesBytes = [System.IO.File]::ReadAllBytes($propertiesPath)
    $content = [System.Text.Encoding]::UTF8.GetString($script:originalServerPropertiesBytes)
    foreach ($entry in ([ordered]@{
        "level-name" = $LevelName
        "level-seed" = $Seed
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
    param([string]$EpisodeId, [string]$LevelName, [string]$ServerJarSha256)
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
        "src/bot/bot_server.js",
        "--host", $MinecraftHost,
        "--port", $MinecraftPort,
        "--username", $Username,
        "--version", "1.20.4",
        "--bridge-port", $BridgePort,
        "--benchmark-seed", "12345",
        "--benchmark-episode", $EpisodeId,
        "--benchmark-level-name", $LevelName,
        "--benchmark-server-jar-sha256", $ServerJarSha256,
        "--craft-max-attempts", "1"
    )
    $script:bridgeProcess = Start-Process -FilePath "node" -ArgumentList $bridgeArgs -WorkingDirectory $repoRoot -RedirectStandardOutput $bridgeStdout -RedirectStandardError $bridgeStderr -WindowStyle Hidden -PassThru
    $health = Wait-ForBridgeSession "127.0.0.1" $BridgePort $BridgeWaitSeconds
    if (-not $health) {
        throw "Bridge did not report bot_ready=true for $EpisodeId."
    }
    $hasCraftPolicy = $health.PSObject.Properties.Name -contains "craft_policy"
    if (-not $hasCraftPolicy -or -not $health.craft_policy -or [int]$health.craft_policy.max_attempts -ne 1) {
        throw "SP-002 bridge did not prove craft max_attempts=1."
    }
}

function Stop-ControlledRuntime {
    Stop-OwnedProcess $script:bridgeProcess
    $script:bridgeProcess = $null
    Start-Sleep -Seconds 2
    Stop-OwnedProcess $script:serverProcess
    $script:serverProcess = $null
}

function Assert-CommonRuntimePreflight {
    Assert-File $jarPath "Pinned Paper server jar is missing at $jarPath."
    Assert-File $eulaPath "eula.txt is missing."
    Assert-File $propertiesPath "server.properties is missing."
    Assert-File $protocolPath "Stone-pickaxe protocol is missing."
    Assert-File $policyPath "SP-002 harness policy is missing."
    Assert-File $authorizationPath "The one-time SP-002 authorization is missing."
    if (-not (Select-String -LiteralPath $eulaPath -Pattern '^\s*eula\s*=\s*true\s*$' -Quiet)) {
        throw "SP-002 runtime requires an already accepted eula=true state."
    }
    if ((Get-ServerProperty $propertiesPath "level-seed") -ne "12345") {
        throw "server.properties must contain level-seed=12345 before runtime."
    }
    if ((Get-ServerProperty $propertiesPath "online-mode") -ne "false") {
        throw "server.properties must contain online-mode=false."
    }
    $opsPath = Join-Path $serverRoot "ops.json"
    Assert-File $opsPath "ops.json is missing."
    $operators = @(Get-Content -LiteralPath $opsPath -Raw -Encoding UTF8 | ConvertFrom-Json)
    if (-not ($operators | Where-Object { $_.name -eq $Username })) {
        throw "$Username must be an operator for the audited fixture save command."
    }
    if (Test-TcpEndpoint $MinecraftHost $MinecraftPort) {
        throw "Minecraft port $MinecraftPort is already occupied."
    }
    if (Test-TcpEndpoint "127.0.0.1" $BridgePort) {
        throw "Bridge port $BridgePort is already occupied."
    }
    $apiKey = Get-ConfiguredApiKey
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        throw "SP-002 runtime requires an LLM credential."
    }
    $protocol = Get-Content -LiteralPath $protocolPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $jarSha256 = (Get-FileHash -LiteralPath $jarPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($jarSha256 -ne [string]$protocol.environment.server_jar_sha256) {
        throw "Pinned Paper jar SHA-256 does not match the stone-pickaxe protocol."
    }
    $env:SINGULARITY_LLM_API_KEY = $apiKey
    $env:SINGULARITY_LLM_BASE_URL = [string]$protocol.planner.base_url
    $env:PYTHONPATH = Join-Path $repoRoot "src"
    return [ordered]@{
        protocol = $protocol
        jar_sha256 = $jarSha256
    }
}

Push-Location $repoRoot
try {
    if ($Mode -eq "AuditSP002Fixture") {
        $env:PYTHONPATH = Join-Path $repoRoot "src"
        Assert-File $fixtureManifestPath "SP-002 fixture manifest does not exist."
        $fixture = Get-Content -LiteralPath $fixtureManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $snapshotRoot = Resolve-FixtureSnapshot $fixture
        & python scripts/stone_pickaxe_episode_runner.py audit-sp002-fixture --fixture "workspace/evals/stone_pickaxe_sp002_fixture.json" --snapshot-root (Get-RepositoryRelativePath $snapshotRoot)
        if ($LASTEXITCODE -ne 0) { throw "SP-002 fixture audit failed." }
        return
    }

    $gitHead = Assert-CleanSynchronizedMain
    $gitParent = Get-AuthorizationParent
    $preflight = Assert-CommonRuntimePreflight
    $protocol = $preflight.protocol
    $serverJarSha256 = [string]$preflight.jar_sha256
    $authorization = Get-Content -LiteralPath $authorizationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $episodeId = [string]$authorization.episode_id
    if ($episodeId -cnotmatch '^[a-z0-9][a-z0-9_-]{0,95}$') {
        throw "SP-002 authorization episode_id is not a bounded lowercase ASCII identifier."
    }
    $levelName = "${episodeId}_world"

    if ($Mode -eq "PrepareSP002Fixture") {
        Assert-File $sourceFixturePath "The immutable SP-001 source fixture is missing."
        if (Test-Path -LiteralPath $fixtureManifestPath) {
            throw "SP-002 fixture already exists; automatic fixture replacement is forbidden."
        }
        $sourceFixture = Get-Content -LiteralPath $sourceFixturePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $sourceSnapshotRoot = Resolve-FixtureSnapshot $sourceFixture
        $sourceSnapshotRelative = Get-RepositoryRelativePath $sourceSnapshotRoot
        & python scripts/stone_pickaxe_episode_runner.py audit-fixture --fixture "workspace/evals/stone_pickaxe_fixture.json" --snapshot-root $sourceSnapshotRelative
        if ($LASTEXITCODE -ne 0) { throw "SP-001 source fixture identity audit failed." }

        $preflightRelative = "logs\stone_pickaxe\sp002_preflights\$episodeId"
        $preflightRoot = Join-Path $repoRoot $preflightRelative
        $preparationRelative = "logs\stone_pickaxe\sp002_fixture_preparations\$episodeId"
        $preparationRoot = Join-Path $repoRoot $preparationRelative
        $snapshotRelative = "logs\stone_pickaxe\fixtures\sp002-craft-stone-pickaxe-v1\$episodeId"
        $snapshotRoot = Assert-PathWithin (Join-Path $repoRoot $snapshotRelative) (Join-Path $repoRoot "logs\stone_pickaxe\fixtures") "SP-002 snapshot destination escaped its controlled root."
        foreach ($path in @($preflightRoot, $preparationRoot, $snapshotRoot)) {
            if (Test-Path -LiteralPath $path) { throw "Controlled SP-002 output already exists: $path" }
        }
        New-Item -ItemType Directory -Path $preflightRoot | Out-Null

        $authorizationAuditRelative = "$preflightRelative\authorization_preflight.json"
        & python scripts/stone_pickaxe_episode_runner.py audit-sp002-authorization --scope fixture_preparation --episode-id $episodeId --git-head $gitHead --git-parent $gitParent --fixture "workspace/evals/stone_pickaxe_fixture.json" --authorization $authorizationRelative --output $authorizationAuditRelative
        if ($LASTEXITCODE -ne 0) { throw "SP-002 fixture-preparation authorization audit failed." }

        Copy-SnapshotToLevel $sourceSnapshotRoot $levelName
        $restorationRelative = "$preflightRelative\restoration.json"
        & python scripts/stone_pickaxe_episode_runner.py audit-restoration --fixture "workspace/evals/stone_pickaxe_fixture.json" --server-root $ServerDirectory --level-name $levelName --output $restorationRelative
        if ($LASTEXITCODE -ne 0) { throw "SP-002 source restoration audit failed." }

        Set-EpisodeServerProperties $levelName ([string]$protocol.environment.world_seed)
        Start-ControlledRuntime $episodeId $levelName $serverJarSha256
        & python scripts/stone_pickaxe_episode_runner.py prepare-sp002-fixture --host $MinecraftHost --port $MinecraftPort --username $Username --bridge-host 127.0.0.1 --bridge-port $BridgePort --episode-id $episodeId --level-name $levelName --output-dir $preparationRelative --source-fixture "workspace/evals/stone_pickaxe_fixture.json" --authorization $authorizationRelative --git-head $gitHead --git-parent $gitParent
        $runnerExit = $LASTEXITCODE
        Stop-ControlledRuntime
        if ($runnerExit -ne 0) {
            throw "The single authorized SP-002 fixture preparation failed; automatic retry is forbidden."
        }

        Copy-LevelToSnapshot $levelName $snapshotRoot
        & python scripts/stone_pickaxe_episode_runner.py seal-sp002-fixture --snapshot-root $snapshotRelative --preparation "$preparationRelative\preparation.json" --output "workspace/evals/stone_pickaxe_sp002_fixture.json"
        if ($LASTEXITCODE -ne 0) { throw "SP-002 snapshot sealing failed." }
        Write-Host "SP-002 fixture prepared and sealed: $snapshotRelative"
        Write-Host "No live SP-002 episode or SP-003 action was started."
        return
    }

    Assert-File $fixtureManifestPath "RunSP002 requires a sealed SP-002 fixture."
    $fixture = Get-Content -LiteralPath $fixtureManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $snapshotRoot = Resolve-FixtureSnapshot $fixture
    $snapshotRelative = Get-RepositoryRelativePath $snapshotRoot
    & python scripts/stone_pickaxe_episode_runner.py audit-sp002-fixture --fixture "workspace/evals/stone_pickaxe_sp002_fixture.json" --snapshot-root $snapshotRelative
    if ($LASTEXITCODE -ne 0) { throw "SP-002 fixture identity audit failed." }

    $outputRelative = "workspace\evals\sp002_runs\$episodeId"
    $outputRoot = Join-Path $repoRoot $outputRelative
    if (Test-Path -LiteralPath $outputRoot) {
        throw "SP-002 evidence directory already exists; support reruns are forbidden: $outputRoot"
    }
    New-Item -ItemType Directory -Path $outputRoot | Out-Null
    $retainedAuthorizationRelative = "$outputRelative\authorization.json"
    Copy-Item -LiteralPath $authorizationPath -Destination (Join-Path $repoRoot $retainedAuthorizationRelative)

    $authorizationAuditRelative = "$outputRelative\authorization_preflight.json"
    & python scripts/stone_pickaxe_episode_runner.py audit-sp002-authorization --scope live_episode --episode-id $episodeId --git-head $gitHead --git-parent $gitParent --fixture "workspace/evals/stone_pickaxe_sp002_fixture.json" --authorization $retainedAuthorizationRelative --output $authorizationAuditRelative
    if ($LASTEXITCODE -ne 0) { throw "SP-002 live authorization audit failed." }

    $hypothesisRelative = "$outputRelative\hypothesis.json"
    & python scripts/stone_pickaxe_episode_runner.py write-sp002-hypothesis --fixture "workspace/evals/stone_pickaxe_sp002_fixture.json" --snapshot-root $snapshotRelative --authorization $retainedAuthorizationRelative --episode-id $episodeId --git-head $gitHead --git-parent $gitParent --output $hypothesisRelative
    if ($LASTEXITCODE -ne 0) { throw "Could not persist the pre-live SP-002 hypothesis." }

    Copy-SnapshotToLevel $snapshotRoot $levelName
    $restorationRelative = "$outputRelative\restoration.json"
    & python scripts/stone_pickaxe_episode_runner.py audit-restoration --fixture "workspace/evals/stone_pickaxe_sp002_fixture.json" --server-root $ServerDirectory --level-name $levelName --output $restorationRelative
    if ($LASTEXITCODE -ne 0) { throw "Restored SP-002 world failed immutable snapshot audit." }

    Set-EpisodeServerProperties $levelName ([string]$protocol.environment.world_seed)
    Start-ControlledRuntime $episodeId $levelName $serverJarSha256
    & python scripts/stone_pickaxe_episode_runner.py run-sp002 --host $MinecraftHost --port $MinecraftPort --username $Username --bridge-host 127.0.0.1 --bridge-port $BridgePort --episode-id $episodeId --level-name $levelName --output-dir $outputRelative --fixture "workspace/evals/stone_pickaxe_sp002_fixture.json" --authorization $retainedAuthorizationRelative --hypothesis $hypothesisRelative --restoration $restorationRelative --git-head $gitHead --git-parent $gitParent --server-jar-sha256 $serverJarSha256
    $runnerExit = $LASTEXITCODE
    Stop-ControlledRuntime
    if ($runnerExit -ne 0) {
        throw "The single authorized SP-002 episode failed; automatic retry is forbidden."
    }
    Write-Host "Single SP-002 episode retained: $outputRelative"
    Write-Host "No retry, SP-003, BM-012, or iron-mining action was started."
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
        Write-Warning ("SP-002 runtime cleanup issues: " + ($cleanupErrors -join "; "))
    }
}

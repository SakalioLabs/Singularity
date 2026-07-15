[CmdletBinding()]
param(
    [ValidateSet("PrepareFixture", "RunSP001", "AuditFixture")]
    [string]$Mode = "AuditFixture",
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
$fixtureManifestPath = Join-Path $repoRoot "workspace\evals\stone_pickaxe_fixture.json"
$runtimeLogRoot = Join-Path $repoRoot "logs\stone_pickaxe\runtime"
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
        throw "Stone-pickaxe runtime requires branch main."
    }
    $status = @(& git status --porcelain)
    if ($LASTEXITCODE -ne 0 -or $status.Count -ne 0) {
        throw "Stone-pickaxe runtime requires a clean worktree before authorization is consumed."
    }
    $head = (& git rev-parse HEAD).Trim()
    $origin = (& git rev-parse origin/main).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -ne $origin) {
        throw "Stone-pickaxe runtime requires HEAD == origin/main."
    }
    return $head
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
    param(
        [string]$EpisodeId,
        [string]$LevelName,
        [string]$ServerJarSha256
    )
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
        "--benchmark-server-jar-sha256", $ServerJarSha256
    )
    $script:bridgeProcess = Start-Process -FilePath "node" -ArgumentList $bridgeArgs -WorkingDirectory $repoRoot -RedirectStandardOutput $bridgeStdout -RedirectStandardError $bridgeStderr -WindowStyle Hidden -PassThru
    if (-not (Wait-ForBridgeSession "127.0.0.1" $BridgePort $BridgeWaitSeconds)) {
        throw "Bridge did not report bot_ready=true for $EpisodeId."
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
    if (-not (Select-String -LiteralPath $eulaPath -Pattern '^\s*eula\s*=\s*true\s*$' -Quiet)) {
        throw "Stone-pickaxe runtime requires an already accepted eula=true state."
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
        throw "Stone-pickaxe runtime requires an LLM credential."
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
    if ($Mode -eq "AuditFixture") {
        $env:PYTHONPATH = Join-Path $repoRoot "src"
        Assert-File $fixtureManifestPath "Fixture manifest does not exist."
        $fixture = Get-Content -LiteralPath $fixtureManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $snapshotRoot = Assert-PathWithin (Join-Path $repoRoot ([string]$fixture.snapshot.path)) (Join-Path $repoRoot "logs\stone_pickaxe\fixtures") "Fixture snapshot path escaped its controlled root."
        & python scripts/stone_pickaxe_episode_runner.py audit-fixture --fixture "workspace/evals/stone_pickaxe_fixture.json" --snapshot-root ([System.IO.Path]::GetRelativePath($repoRoot, $snapshotRoot))
        if ($LASTEXITCODE -ne 0) { throw "Fixture audit failed." }
        return
    }

    $gitHead = Assert-CleanSynchronizedMain
    $preflight = Assert-CommonRuntimePreflight
    $protocol = $preflight.protocol
    $serverJarSha256 = [string]$preflight.jar_sha256
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $suffix = [guid]::NewGuid().ToString('N').Substring(0, 8)

    if ($Mode -eq "PrepareFixture") {
        if (Test-Path -LiteralPath $fixtureManifestPath) {
            throw "Fixture manifest already exists; automatic fixture replacement is forbidden."
        }
        $episodeId = "sp_fixture_prep_${timestamp}_${suffix}"
        $levelName = $episodeId
        $preparationRelative = "logs\stone_pickaxe\fixture_preparations\$episodeId"
        $preparationRoot = Join-Path $repoRoot $preparationRelative
        $snapshotRelative = "logs\stone_pickaxe\fixtures\sp001-acquire-cobblestone-v1\$episodeId"
        $snapshotRoot = Assert-PathWithin (Join-Path $repoRoot $snapshotRelative) (Join-Path $repoRoot "logs\stone_pickaxe\fixtures") "Snapshot destination escaped its controlled root."
        foreach ($path in @($preparationRoot, $snapshotRoot)) {
            if (Test-Path -LiteralPath $path) { throw "Controlled output already exists: $path" }
        }
        foreach ($worldName in @($levelName, "${levelName}_nether", "${levelName}_the_end")) {
            $worldPath = Assert-PathWithin (Join-Path $serverRoot $worldName) $serverRoot "Fresh world path escaped the server root."
            if (Test-Path -LiteralPath $worldPath) { throw "Fresh fixture world already exists: $worldPath" }
        }

        Set-EpisodeServerProperties $levelName ([string]$protocol.environment.world_seed)
        Start-ControlledRuntime $episodeId $levelName $serverJarSha256
        & python scripts/stone_pickaxe_episode_runner.py prepare-fixture --host $MinecraftHost --port $MinecraftPort --username $Username --bridge-host 127.0.0.1 --bridge-port $BridgePort --episode-id $episodeId --level-name $levelName --output-dir $preparationRelative
        $runnerExit = $LASTEXITCODE
        Stop-ControlledRuntime
        if ($runnerExit -ne 0) {
            throw "The one authorized fixture-preparation session did not pass machine audit; no retry is allowed."
        }

        New-Item -ItemType Directory -Path $snapshotRoot | Out-Null
        $sourceNames = @($levelName, "${levelName}_nether", "${levelName}_the_end")
        $targetNames = @("world", "world_nether", "world_the_end")
        for ($index = 0; $index -lt $sourceNames.Count; $index++) {
            $source = Assert-PathWithin (Join-Path $serverRoot $sourceNames[$index]) $serverRoot "Snapshot source escaped the server root."
            $target = Assert-PathWithin (Join-Path $snapshotRoot $targetNames[$index]) $snapshotRoot "Snapshot target escaped the snapshot root."
            if (-not (Test-Path -LiteralPath $source -PathType Container)) {
                throw "Expected saved world component is missing: $source"
            }
            if (Test-Path -LiteralPath $target) { throw "Snapshot target already exists: $target" }
            Copy-Item -LiteralPath $source -Destination $target -Recurse
        }
        $preparationPath = "$preparationRelative\preparation.json"
        & python scripts/stone_pickaxe_episode_runner.py seal-fixture --snapshot-root $snapshotRelative --preparation $preparationPath --output "workspace/evals/stone_pickaxe_fixture.json"
        if ($LASTEXITCODE -ne 0) { throw "Snapshot sealing failed; no live episode is allowed." }
        Write-Host "Fixture prepared and sealed: $snapshotRelative"
        Write-Host "Tracked manifest: workspace/evals/stone_pickaxe_fixture.json"
        return
    }

    Assert-File $fixtureManifestPath "RunSP001 requires a sealed fixture manifest."
    $fixture = Get-Content -LiteralPath $fixtureManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $snapshotRoot = Assert-PathWithin (Join-Path $repoRoot ([string]$fixture.snapshot.path)) (Join-Path $repoRoot "logs\stone_pickaxe\fixtures") "Fixture snapshot path escaped its controlled root."
    $snapshotRelative = [System.IO.Path]::GetRelativePath($repoRoot, $snapshotRoot)
    & python scripts/stone_pickaxe_episode_runner.py audit-fixture --fixture "workspace/evals/stone_pickaxe_fixture.json" --snapshot-root $snapshotRelative
    if ($LASTEXITCODE -ne 0) { throw "Fixture identity audit failed before live authorization consumption." }

    $episodeId = "sp001_episode_${timestamp}_${suffix}"
    $levelName = $episodeId
    $outputRelative = "workspace\evals\sp001_runs\$episodeId"
    $outputRoot = Join-Path $repoRoot $outputRelative
    if (Test-Path -LiteralPath $outputRoot) { throw "SP-001 evidence directory already exists: $outputRoot" }
    $hypothesisRelative = "$outputRelative\hypothesis.json"
    & python scripts/stone_pickaxe_episode_runner.py write-hypothesis --fixture "workspace/evals/stone_pickaxe_fixture.json" --snapshot-root $snapshotRelative --episode-id $episodeId --git-head $gitHead --output $hypothesisRelative
    if ($LASTEXITCODE -ne 0) { throw "Could not persist the pre-episode hypothesis." }

    $sourceNames = @("world", "world_nether", "world_the_end")
    $targetNames = @($levelName, "${levelName}_nether", "${levelName}_the_end")
    for ($index = 0; $index -lt $sourceNames.Count; $index++) {
        $source = Assert-PathWithin (Join-Path $snapshotRoot $sourceNames[$index]) $snapshotRoot "Restoration source escaped the snapshot root."
        $target = Assert-PathWithin (Join-Path $serverRoot $targetNames[$index]) $serverRoot "Restoration target escaped the server root."
        if (-not (Test-Path -LiteralPath $source -PathType Container)) { throw "Snapshot component is missing: $source" }
        if (Test-Path -LiteralPath $target) { throw "Fresh SP-001 world already exists: $target" }
        Copy-Item -LiteralPath $source -Destination $target -Recurse
    }
    $restorationRelative = "$outputRelative\restoration.json"
    & python scripts/stone_pickaxe_episode_runner.py audit-restoration --fixture "workspace/evals/stone_pickaxe_fixture.json" --server-root $ServerDirectory --level-name $levelName --output $restorationRelative
    if ($LASTEXITCODE -ne 0) { throw "Restored episode world failed the immutable snapshot audit." }

    Set-EpisodeServerProperties $levelName ([string]$protocol.environment.world_seed)
    Start-ControlledRuntime $episodeId $levelName $serverJarSha256
    & python scripts/stone_pickaxe_episode_runner.py run-sp001 --host $MinecraftHost --port $MinecraftPort --username $Username --bridge-host 127.0.0.1 --bridge-port $BridgePort --episode-id $episodeId --level-name $levelName --output-dir $outputRelative --fixture "workspace/evals/stone_pickaxe_fixture.json" --hypothesis $hypothesisRelative --restoration $restorationRelative --server-jar-sha256 $serverJarSha256
    $runnerExit = $LASTEXITCODE
    Stop-ControlledRuntime
    if ($runnerExit -ne 0) {
        throw "The single authorized SP-001 episode hit a runtime blocker; automatic retry is forbidden."
    }
    Write-Host "Single SP-001 episode retained: $outputRelative"
    Write-Host "No retry, SP-002, SP-003, BM-012, or iron-mining action was started."
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
        Write-Warning ("Stone-pickaxe runtime cleanup issues: " + ($cleanupErrors -join "; "))
    }
}

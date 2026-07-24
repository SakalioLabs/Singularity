param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9][a-z0-9_-]{0,95}$')]
    [string]$EpisodeId,
    [string]$ServerDirectory = "mc-server",
    [string]$ServerJar = "server.jar",
    [string]$MinecraftHost = "127.0.0.1",
    [int]$MinecraftPort = 25565,
    [string]$Username = "Singularity",
    [int]$BridgePort = 30000,
    [string]$BaseUrl = "http://192.168.3.27:8317",
    [string]$Model = "grok-4.5",
    [int]$ServerWaitSeconds = 240,
    [int]$BridgeWaitSeconds = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$serverRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot $ServerDirectory))
$jarPath = Join-Path $serverRoot $ServerJar
$eulaPath = Join-Path $serverRoot "eula.txt"
$propertiesPath = Join-Path $serverRoot "server.properties"
$opsPath = Join-Path $serverRoot "ops.json"
$levelName = "${EpisodeId}_world"
$runRelative = "workspace/evals/sp004_runs/$EpisodeId"
$runRoot = Join-Path $repoRoot $runRelative
$probeRelative = "workspace/evals/sp004_provider_probes/${EpisodeId}_provider.json"
$probeRoot = Join-Path $repoRoot $probeRelative
$runtimeLogRoot = Join-Path $repoRoot "logs/sp004_runtime"
$serverProcess = $null
$bridgeProcess = $null
$originalServerProperties = $null
$serverPropertiesModified = $false

function Assert-File {
    param([string]$Path, [string]$Message)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw $Message }
}

function Test-TcpEndpoint {
    param([string]$HostName, [int]$Port, [int]$TimeoutMs = 1000)
    $client = [Net.Sockets.TcpClient]::new()
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

function Invoke-BridgeCommand {
    param([string]$Command, [hashtable]$Parameters = @{})
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $client.ReceiveTimeout = 10000
        $client.SendTimeout = 10000
        $client.Connect("127.0.0.1", $BridgePort)
        $stream = $client.GetStream()
        $payload = @{ command = $Command; params = $Parameters } |
            ConvertTo-Json -Compress -Depth 12
        $bytes = [Text.Encoding]::UTF8.GetBytes($payload + "`n")
        $stream.Write($bytes, 0, $bytes.Length)
        $reader = [IO.StreamReader]::new(
            $stream,
            [Text.Encoding]::UTF8,
            $false,
            4096,
            $true
        )
        $line = $reader.ReadLine()
        if (-not $line) { throw "Bridge returned an empty response for $Command." }
        return $line | ConvertFrom-Json
    }
    finally { $client.Dispose() }
}

function Wait-ForBridge {
    param([int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-BridgeCommand "health"
            if ($health.success -eq $true -and $health.bot_ready -eq $true) {
                return $health
            }
        }
        catch {}
        Start-Sleep -Seconds 1
    }
    return $null
}

function Stop-OwnedProcess {
    param($Process)
    if ($Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id -ErrorAction SilentlyContinue
        $Process.WaitForExit(10000) | Out-Null
    }
}

function Assert-SynchronizedProtectedState {
    $branch = (& git branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or $branch -ne "main") {
        throw "SP-004 runtime requires branch main."
    }
    $head = (& git rev-parse HEAD).Trim()
    $origin = (& git rev-parse origin/main).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -ne $origin) {
        throw "SP-004 runtime requires HEAD == origin/main."
    }
    $protected = @(
        "scripts/iron-pickaxe-sp004-runtime.ps1",
        "scripts/iron_pickaxe_sp004_episode_runner.py",
        "scripts/iron_pickaxe_sp004_provider_probe.py",
        "src/bot/sp004_bot_server.js",
        "src/singularity/evaluation/iron_pickaxe_sp004_runtime.py"
    )
    & git diff --quiet HEAD -- @protected
    if ($LASTEXITCODE -ne 0) {
        throw "SP-004 protected runtime files differ from HEAD."
    }
    return $head
}

function Set-ServerProperty {
    param([string]$Content, [string]$Name, [string]$Value)
    $pattern = "(?m)^\s*$([regex]::Escape($Name))\s*=.*$"
    if ([regex]::IsMatch($Content, $pattern)) {
        return [regex]::Replace($Content, $pattern, "$Name=$Value")
    }
    return $Content.TrimEnd() + [Environment]::NewLine +
        "$Name=$Value" + [Environment]::NewLine
}

function Set-EpisodeServerProperties {
    $script:originalServerProperties = [IO.File]::ReadAllBytes($propertiesPath)
    $content = [Text.Encoding]::UTF8.GetString($script:originalServerProperties)
    foreach ($entry in ([ordered]@{
        "level-name" = $levelName
        "level-seed" = "12345"
        "server-port" = [string]$MinecraftPort
        "online-mode" = "false"
        "gamemode" = "survival"
        "difficulty" = "peaceful"
        "spawn-monsters" = "false"
        "allow-flight" = "true"
    }).GetEnumerator()) {
        $content = Set-ServerProperty $content $entry.Key $entry.Value
    }
    [IO.File]::WriteAllText(
        $propertiesPath,
        $content,
        [Text.UTF8Encoding]::new($false)
    )
    $script:serverPropertiesModified = $true
}

function Assert-FreshPaths {
    foreach ($path in @($runRoot, $probeRoot)) {
        if (Test-Path -LiteralPath $path) {
            throw "SP-004 refuses to overwrite evidence: $path"
        }
    }
    foreach ($name in @($levelName, "${levelName}_nether", "${levelName}_the_end")) {
        $world = [IO.Path]::GetFullPath((Join-Path $serverRoot $name))
        if (Test-Path -LiteralPath $world) {
            throw "SP-004 requires a fresh world: $world"
        }
    }
}

function Initialize-AuditedFixture {
    $state = Invoke-BridgeCommand "get_player_state"
    $x = [math]::Floor([double]$state.position.x)
    $y = 200
    $z = [math]::Floor([double]$state.position.z)
    foreach ($message in @(
        "/clear @s",
        "/give @s minecraft:stone_pickaxe 1",
        "/give @s minecraft:stick 2",
        "/time set day",
        "/weather clear",
        "/setblock $x $($y - 1) $z minecraft:cobblestone",
        "/forceload add $($x - 12) $($z - 2) $($x + 12) $($z + 16)",
        "/tp @s $($x + 0.5) $y $($z + 0.5)"
    )) {
        $result = Invoke-BridgeCommand "chat" @{ message = $message }
        if ($result.success -ne $true) {
            throw "SP-004 fixture bootstrap command failed: $message"
        }
        Start-Sleep -Milliseconds 250
    }
    Start-Sleep -Seconds 1

    $commands = [Collections.Generic.List[string]]::new()
    foreach ($command in @(
        "/fill $($x - 2) $($y - 1) $($z - 1) $($x + 2) $($y - 1) $($z + 2) minecraft:cobblestone",
        "/fill $($x - 2) $y $($z - 1) $($x + 2) $($y + 2) $($z + 2) minecraft:air",
        "/fill $($x - 2) $($y - 1) $($z + 3) $($x + 2) $($y - 1) $($z + 15) minecraft:cobblestone",
        "/fill $($x - 2) $y $($z + 3) $($x + 2) $($y + 2) $($z + 15) minecraft:air",
        "/fill $($x - 9) $($y - 1) $($z + 5) $($x + 9) $($y - 1) $($z + 7) minecraft:cobblestone",
        "/fill $($x - 9) $y $($z + 5) $($x + 9) $($y + 2) $($z + 7) minecraft:air",
        "/fill $($x - 10) $($y - 1) $($z + 9) $($x + 10) $($y - 1) $($z + 11) minecraft:cobblestone",
        "/fill $($x - 10) $y $($z + 9) $($x + 10) $($y + 2) $($z + 11) minecraft:air",
        "/fill $($x - 3) $($y - 1) $($z + 13) $($x + 3) $($y - 1) $($z + 15) minecraft:cobblestone",
        "/fill $($x - 3) $y $($z + 13) $($x + 3) $($y + 2) $($z + 15) minecraft:air",
        "/setblock $($x + 4) $y $($z + 2) minecraft:crafting_table"
    )) { $commands.Add($command) }
    foreach ($offset in @(-8, -6, -4, -2, 2, 4, 6, 8)) {
        $commands.Add("/setblock $($x + $offset) $y $($z + 6) minecraft:stone")
    }
    foreach ($offset in @(-9, -7, -5, -3, -1, 1, 3, 5, 7, 9)) {
        $commands.Add("/setblock $($x + $offset) $y $($z + 10) minecraft:coal_ore")
    }
    foreach ($offset in @(-2, 0, 2)) {
        $commands.Add("/setblock $($x + $offset) $y $($z + 14) minecraft:iron_ore")
    }
    foreach ($message in $commands) {
        $result = Invoke-BridgeCommand "chat" @{ message = $message }
        if ($result.success -ne $true) {
            throw "SP-004 fixture command failed: $message"
        }
        Start-Sleep -Milliseconds 250
    }
    Start-Sleep -Seconds 2
    $fixtureState = Invoke-BridgeCommand "get_player_state"
    $supportState = Invoke-BridgeCommand "get_block_below"
    if ([math]::Abs([double]$fixtureState.position.y - [double]$y) -gt 0.1) {
        throw "SP-004 fixture player is not stabilized at Y=$y."
    }
    if ([string]$supportState.block -ne "cobblestone") {
        throw "SP-004 fixture support floor is not machine-observed cobblestone."
    }
    foreach ($sentinel in @(
        @{ x = $x - 8; z = $z + 6 },
        @{ x = $x + 8; z = $z + 6 },
        @{ x = $x - 9; z = $z + 10 },
        @{ x = $x + 9; z = $z + 10 },
        @{ x = $x - 2; z = $z + 14 },
        @{ x = $x + 2; z = $z + 14 }
    )) {
        $floorState = Invoke-BridgeCommand "get_block_at" @{
            x = $sentinel.x
            y = $y - 1
            z = $sentinel.z
        }
        if ([string]$floorState.block -ne "cobblestone") {
            throw "SP-004 fixture resource floor sentinel at $($sentinel.x),$($y - 1),$($sentinel.z) is $($floorState.block), not cobblestone."
        }
    }
    $inventory = Invoke-BridgeCommand "get_inventory"
    $counts = @{}
    foreach ($item in @($inventory.items)) {
        $counts[[string]$item.name] = [int]$item.count
    }
    if ($counts["stone_pickaxe"] -ne 1 -or $counts["stick"] -ne 2) {
        throw "SP-004 fixture inventory does not match stone_pickaxe:1, stick:2."
    }
}

Push-Location $repoRoot
try {
    Assert-File $jarPath "Pinned Paper server jar is missing."
    Assert-File $eulaPath "eula.txt is missing."
    Assert-File $propertiesPath "server.properties is missing."
    Assert-File $opsPath "ops.json is missing."
    if (-not (Select-String $eulaPath -Pattern '^\s*eula\s*=\s*true\s*$' -Quiet)) {
        throw "SP-004 runtime requires eula=true."
    }
    $operators = @(Get-Content $opsPath -Raw -Encoding UTF8 | ConvertFrom-Json)
    if (-not ($operators | Where-Object { $_.name -eq $Username })) {
        throw "$Username must be a server operator."
    }
    if (Test-TcpEndpoint $MinecraftHost $MinecraftPort) {
        throw "Minecraft port $MinecraftPort is already occupied."
    }
    if (Test-TcpEndpoint "127.0.0.1" $BridgePort) {
        throw "Bridge port $BridgePort is already occupied."
    }
    Assert-FreshPaths
    $gitHead = Assert-SynchronizedProtectedState

    $env:PYTHONPATH = Join-Path $repoRoot "src"
    & python scripts/iron_pickaxe_sp004_provider_probe.py `
        --output $probeRelative `
        --base-url $BaseUrl `
        --model $Model
    if ($LASTEXITCODE -ne 0) {
        throw "SP-004 provider recovery gate failed before Minecraft startup."
    }

    Set-EpisodeServerProperties
    New-Item -ItemType Directory -Force -Path $runtimeLogRoot | Out-Null
    $serverStdout = Join-Path $runtimeLogRoot "server_${EpisodeId}.stdout.log"
    $serverStderr = Join-Path $runtimeLogRoot "server_${EpisodeId}.stderr.log"
    $script:serverProcess = Start-Process java -ArgumentList @(
        "-Xms1G", "-Xmx2G", "-jar", $ServerJar, "nogui"
    ) -WorkingDirectory $serverRoot -RedirectStandardOutput $serverStdout `
        -RedirectStandardError $serverStderr -WindowStyle Hidden -PassThru
    if (-not (Wait-ForTcpEndpoint $MinecraftHost $MinecraftPort $ServerWaitSeconds)) {
        throw "Minecraft did not become ready."
    }

    $jarSha256 = (Get-FileHash $jarPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $bridgeStdout = Join-Path $runtimeLogRoot "bridge_${EpisodeId}.stdout.log"
    $bridgeStderr = Join-Path $runtimeLogRoot "bridge_${EpisodeId}.stderr.log"
    $bridgeArgs = @(
        "src/bot/sp004_bot_server.js",
        "--host", $MinecraftHost,
        "--port", $MinecraftPort,
        "--username", $Username,
        "--version", "1.20.4",
        "--bridge-port", $BridgePort,
        "--benchmark-seed", "12345",
        "--benchmark-episode", $EpisodeId,
        "--benchmark-level-name", $levelName,
        "--benchmark-server-jar-sha256", $jarSha256,
        "--craft-max-attempts", "1"
    )
    $script:bridgeProcess = Start-Process node -ArgumentList $bridgeArgs `
        -WorkingDirectory $repoRoot -RedirectStandardOutput $bridgeStdout `
        -RedirectStandardError $bridgeStderr -WindowStyle Hidden -PassThru
    $health = Wait-ForBridge $BridgeWaitSeconds
    if (-not $health) { throw "SP-004 bridge did not become ready." }
    if ($health.smelt_policy.max_attempts -ne 1 -or
        $health.smelt_policy.automatic_retry -ne $false -or
        "iron_ingot" -notin @($health.smelt_policy.supported_outputs) -or
        "coal" -notin @($health.smelt_policy.supported_fuels)) {
        throw "SP-004 bridge smelt policy preflight failed."
    }

    Initialize-AuditedFixture
    & python scripts/iron_pickaxe_sp004_episode_runner.py run `
        --episode-id $EpisodeId `
        --output-dir $runRelative `
        --run-once `
        --host $MinecraftHost `
        --port $MinecraftPort `
        --username $Username `
        --bridge-host 127.0.0.1 `
        --bridge-port $BridgePort `
        --base-url $BaseUrl `
        --model $Model `
        --max-cycles 120 `
        --max-actions 90 `
        --max-duration-s 1800
    if ($LASTEXITCODE -ne 0) {
        throw "SP-004 episode failed; evidence was retained and no retry is allowed."
    }
    Write-Host "SP-004 episode passed: $runRelative at $gitHead"
}
finally {
    Stop-OwnedProcess $bridgeProcess
    Start-Sleep -Seconds 2
    Stop-OwnedProcess $serverProcess
    if ($serverPropertiesModified -and $null -ne $originalServerProperties) {
        [IO.File]::WriteAllBytes($propertiesPath, $originalServerProperties)
    }
    Pop-Location
}

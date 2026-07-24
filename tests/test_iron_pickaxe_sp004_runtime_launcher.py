from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts/iron-pickaxe-sp004-runtime.ps1"
BOT_SERVER = ROOT / "src/bot/sp004_bot_server.js"


def _text() -> str:
    return LAUNCHER.read_text(encoding="utf-8")


def test_provider_gate_precedes_every_process_start() -> None:
    text = _text()
    gate = text.index("iron_pickaxe_sp004_provider_probe.py")
    first_start = text.index("Start-Process java")

    assert gate < first_start
    assert "if ($LASTEXITCODE -ne 0)" in text[gate:first_start]
    assert "failed before Minecraft startup" in text[gate:first_start]


def test_launcher_uses_isolated_bridge_and_exact_runtime_bounds() -> None:
    text = _text()

    assert "src/bot/sp004_bot_server.js" in text
    assert "iron_pickaxe_sp004_episode_runner.py run" in text
    assert "--run-once" in text
    assert "--max-cycles 120" in text
    assert "--max-actions 90" in text
    assert "--max-duration-s 1800" in text
    assert '--craft-max-attempts", "1"' in text


def test_launcher_builds_exact_audited_fixture() -> None:
    text = _text()

    assert "/give @s minecraft:stone_pickaxe 1" in text
    assert "/give @s minecraft:stick 2" in text
    assert "minecraft:crafting_table" in text
    assert "minecraft:cobblestone" in text
    assert 'minecraft:air"' in text
    assert '"/tp @s $($x + 0.5) $y $($z + 0.5)"' in text
    assert "$y = 200" in text
    assert 'Invoke-BridgeCommand "get_block_below"' in text
    assert 'Invoke-BridgeCommand "get_block_at"' in text
    assert 'supportState.block -ne "cobblestone"' in text
    assert 'floorState.block -ne "cobblestone"' in text
    assert "fixture player is not stabilized" in text
    assert '"allow-flight" = "true"' in text
    assert "/setblock $x $($y - 1) $z minecraft:cobblestone" in text
    assert "/forceload add" in text
    assert text.index("/forceload add") < text.index(
        '"/fill $($x - 2) $($y - 1)'
    )
    assert "is $($floorState.block), not cobblestone" in text
    assert "$($y - 1)" in text
    assert "$($y + 2)" in text
    assert text.count("minecraft:stone") == 2
    assert "minecraft:coal_ore" in text
    assert "minecraft:iron_ore" in text
    assert "@(-8, -6, -4, -2, 2, 4, 6, 8)" in text
    assert "@(-9, -7, -5, -3, -1, 1, 3, 5, 7, 9)" in text
    assert "@(-2, 0, 2)" in text


def test_bridge_exposes_exact_fixture_block_observation() -> None:
    text = BOT_SERVER.read_text(encoding="utf-8")

    assert "get_block_at: (params) =>" in text
    assert "coordinates.every(Number.isFinite)" in text
    assert "compactPosition(position)" in text


def test_launcher_always_stops_owned_processes_and_restores_properties() -> None:
    text = _text()
    finally_block = text[text.rindex("finally {") :]

    assert "Stop-OwnedProcess $bridgeProcess" in finally_block
    assert "Stop-OwnedProcess $serverProcess" in finally_block
    assert "[IO.File]::WriteAllBytes($propertiesPath, $originalServerProperties)" in (
        finally_block
    )
    assert "Pop-Location" in finally_block


def test_launcher_does_not_embed_credentials() -> None:
    text = _text().lower()

    assert "github_pat_" not in text
    assert "api_key =" not in text
    assert "openai_api_key=" not in text

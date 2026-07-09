# Singularity Setup Script
# Run: .\setup.ps1

Write-Host "=== Singularity Minecraft LLM Agent Setup ===" -ForegroundColor Cyan

# 1. Python package and dependencies
Write-Host "`n[1/3] Installing the Python package and dependencies..." -ForegroundColor Yellow
python -m pip install -e .

# 2. Node.js dependencies
Write-Host "`n[2/3] Installing Node.js dependencies..." -ForegroundColor Yellow
npm install

# 3. Verify
Write-Host "`n[3/3] Verifying installation..." -ForegroundColor Yellow
python -c "import singularity; import openai; import anthropic; import pydantic; print('Python package and deps OK')"
node -e "const m = require('mineflayer'); const p = require('mineflayer-pathfinder'); console.log('Node deps OK')"

Write-Host "`n=== Setup Complete ===" -ForegroundColor Green
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Start MC server: cd mc-server; java -Xmx1G -jar server.jar nogui"
Write-Host "  2. Start bot: node src/bot/bot_server.js"
Write-Host "  3. Run agent: python -m singularity.main run --goal 'Gather 3 oak logs'"
Write-Host "  4. Run benchmarks: python -m singularity.main benchmark --suite m1"
Write-Host "  5. M2 test (needs OPENAI_API_KEY): python tests/test_m2_integration.py"

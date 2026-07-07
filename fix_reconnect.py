import pathlib
p = pathlib.Path(r"C:\Users\Administrator\Documents\Singularity\src\bot\bot_server.js")
c = p.read_text(encoding="utf-8")
# Rename and add auto-reconnect
c = c.replace("function createBot() {", "function connectBot() {")
c = c.replace("createBot();", "connectBot();")
c = c.replace("""    bot.on('end', () => console.log('[Bot] Disconnected'));""",
"""    bot.on('end', () => {
        console.log('[Bot] Disconnected - reconnecting in 5s');
        setTimeout(connectBot, 5000);
    });""")
p.write_text(c, encoding="utf-8")
print("Auto-reconnect added to bridge")

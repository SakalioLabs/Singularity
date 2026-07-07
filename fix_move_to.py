import pathlib
p = pathlib.Path(r"C:\Users\Administrator\Documents\Singularity\src\bot\bot_server.js")
c = p.read_text(encoding="utf-8")
old = """    move_to: async (params) => {
        const MOVE_TIMEOUT = 2000;
        try {
            const goal = new goals.GoalNear(params.x, params.y || bot.entity.position.y, params.z, 1);
            const result = await Promise.race([
                bot.pathfinder.goto(goal).then(() => ({ ok: true })),
                new Promise((_, rej) => setTimeout(() => rej(new Error('Pathfinding timeout')), MOVE_TIMEOUT))
            ]);
            return { success: true, position: bot.entity.position };
        } catch (e) {
            bot.pathfinder.stop();
            return { success: false, error: e.message };
        }
    },"""
new = """    move_to: (params) => {
        const goal = new goals.GoalNear(params.x, params.y || bot.entity.position.y, params.z, 1);
        bot.pathfinder.goto(goal).catch(() => {});
        return { success: true, status: "moving", position: bot.entity.position };
    },"""
if old in c:
    c = c.replace(old, new)
    p.write_text(c, encoding="utf-8")
    print("Fixed: move_to is now non-blocking")
else:
    print("ERROR: old pattern not found!")
    # Show context around move_to
    lines = c.split("\n")
    for i, line in enumerate(lines):
        if "move_to" in line:
            for j in range(max(0,i-2), min(len(lines), i+15)):
                print(f"  {j}: {lines[j]}")

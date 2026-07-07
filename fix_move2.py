import pathlib
p = pathlib.Path(r"C:\Users\Administrator\Documents\Singularity\src\bot\bot_server.js")
c = p.read_text(encoding="utf-8")
old = '''    move_to: (params) => {
        const goal = new goals.GoalNear(params.x, params.y || bot.entity.position.y, params.z, 1);
        bot.pathfinder.goto(goal).catch(() => {});
        return { success: true, status: "moving", position: bot.entity.position };
    },'''
new = '''    move_to: async (params) => {
        try {
            const goal = new goals.GoalNear(params.x, params.y || bot.entity.position.y, params.z, 1);
            bot.pathfinder.stop();
            await bot.pathfinder.goto(goal);
            return { success: true, position: bot.entity.position };
        } catch (e) {
            bot.pathfinder.stop();
            return { success: false, error: e.message };
        }
    },'''
if old in c:
    c = c.replace(old, new)
    p.write_text(c, encoding="utf-8")
    print("Fixed: move_to now stops previous pathfinder before starting new one")
else:
    print("ERROR: old pattern not found")

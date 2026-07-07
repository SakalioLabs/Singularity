import pathlib
p = pathlib.Path(r"C:\Users\Administrator\Documents\Singularity\src\bot\bot_server.js")
c = p.read_text(encoding="utf-8")
# Replace move_to with a simple direct approach
old = '''    move_to: async (params) => {
        const goal = new goals.GoalNear(params.x, params.y || bot.entity.position.y, params.z, 1);
        try {
            await bot.pathfinder.goto(goal);
            return { success: true, position: bot.entity.position };
        } catch (e) {
            bot.pathfinder.stop();
            return { success: false, error: e.message };
        }
    },'''
new = '''    move_to: async (params) => {
        const target = new Vec3(params.x, params.y || bot.entity.position.y, params.z);
        try {
            await bot.lookAt(target);
            bot.setControlState("forward", true);
            let waited = 0;
            while (bot.entity.position.distanceTo(target) > 2 && waited < 3000) {
                await new Promise(r => setTimeout(r, 100));
                bot.lookAt(target);
                waited += 100;
            }
            bot.setControlState("forward", false);
            return { success: true, position: bot.entity.position };
        } catch (e) {
            bot.setControlState("forward", false);
            return { success: false, error: e.message };
        }
    },'''
if old in c:
    c = c.replace(old, new)
    p.write_text(c, encoding="utf-8")
    print("Fixed! move_to now uses direct walking with lookAt")
else:
    print("ERROR: pattern not found")
    # Try to find alternative pattern
    idx = c.find("move_to: async")
    if idx > 0:
        print(f"Found pattern at {idx}")

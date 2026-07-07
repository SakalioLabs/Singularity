import pathlib
p = pathlib.Path(r"C:\Users\Administrator\Documents\Singularity\src\bot\bot_server.js")
c = p.read_text(encoding="utf-8")

# Remove problematic blocksToAvoid lines
c = c.replace("        defaultMove.blocksToAvoid.delete(mcData.blocksByName.leaves?.id);\n", "")
c = c.replace("        defaultMove.blocksToAvoid.delete(mcData.blocksByName.oak_leaves?.id);\n", "")

# Check for hasOak_log
target_func = """    move_to: async (params) => {
        try {
            const goal = new goals.GoalNear(params.x, params.y || bot.entity.position.y, params.z, 1);
            bot.pathfinder.stop();
            await bot.pathfinder.goto(goal);
            return { success: true, position: bot.entity.position };
        } catch (e) {
            bot.pathfinder.stop();
            return { success: false, error: e.message };
        }
    },"""

new_func = """    walk_to: async (params) => {
        const target = new Vec3(params.x, params.y || bot.entity.position.y, params.z);
        try {
            await bot.lookAt(target);
            bot.setControlState("forward", true);
            const maxTime = params.ms || 2000;
            await new Promise(r => setTimeout(r, maxTime));
            bot.setControlState("forward", false);
            return { success: true, position: bot.entity.position };
        } catch (e) {
            bot.setControlState("forward", false);
            return { success: false, error: e.message };
        }
    },
    move_to: async (params) => {
        const goal = new goals.GoalNear(params.x, params.y || bot.entity.position.y, params.z, 1);
        try {
            await bot.pathfinder.goto(goal);
            return { success: true, position: bot.entity.position };
        } catch (e) {
            bot.pathfinder.stop();
            return { success: false, error: e.message };
        }
    },"""

if target_func in c:
    c = c.replace(target_func, new_func)
    p.write_text(c, encoding="utf-8")
    print("Fixed! Added walk_to and cleaned move_to")
else:
    print("ERROR: move_to pattern not found")
    for i, line in enumerate(c.split("\n")):
        if "move_to" in line:
            for j in range(i, min(i+12, len(c.split("\n")))):
                print(f"  {j}: {c.split(chr(10))[j]}")
            break

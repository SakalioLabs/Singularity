import pathlib
p = pathlib.Path(r"C:\Users\Administrator\Documents\Singularity\src\singularity\core\rule_planner.py")
c = p.read_text(encoding="utf-8")
# Find the tree navigation actions and add wait
old = '                        {"type": "move_to", "parameters": {"x": tpos.get("x", 0), "z": tpos.get("z", 0)}},\n                        {"type": "dig", "parameters": {"x": tpos.get("x", 0), "y": tpos.get("y", 0), "z": tpos.get("z", 0)}},'
new = '                        {"type": "move_to", "parameters": {"x": tpos.get("x", 0), "z": tpos.get("z", 0)}},\n                        {"type": "wait", "parameters": {"ms": 1500}},\n                        {"type": "dig", "parameters": {"x": tpos.get("x", 0), "y": tpos.get("y", 0), "z": tpos.get("z", 0)}},'
c = c.replace(old, new)
p.write_text(c, encoding="utf-8")
print("Done")

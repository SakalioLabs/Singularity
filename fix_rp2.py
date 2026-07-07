import pathlib
p = pathlib.Path(r"C:\Users\Administrator\Documents\Singularity\src\singularity\core\rule_planner.py")
c = p.read_text(encoding="utf-8")
old = '                    {"type": "move_to", "parameters": {"x": tpos.get("x", 0), "z": tpos.get("z", 0)}},\n                    {"type": "dig", "parameters": {"x": tpos.get("x", 0), "y": tpos.get("y", 0), "z": tpos.get("z", 0)}}\n                ]'
new = '                    {"type": "walk_to", "parameters": {"x": tpos.get("x", 0), "z": tpos.get("z", 0), "ms": 1500}},\n                    {"type": "dig", "parameters": {"x": tpos.get("x", 0), "y": tpos.get("y", 0), "z": tpos.get("z", 0)}}\n                ]'
if old in c:
    c = c.replace(old, new)
    p.write_text(c, encoding="utf-8")
    print("Fixed!")
else:
    print("ERROR: pattern not found")

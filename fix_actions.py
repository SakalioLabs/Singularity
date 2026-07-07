import pathlib
# Fix action controller
p = pathlib.Path(r"C:\Users\Administrator\Documents\Singularity\src\singularity\action\controller.py")
c = p.read_text(encoding="utf-8")
old = '        self._action_handlers = {'
new = '        self._action_handlers = {\n            "walk_to": self._walk_to,'
if old in c:
    c = c.replace(old, new)
    p.write_text(c, encoding="utf-8")
    print("Added walk_to handler")
old_end = '    def _wait(self, params: dict) -> dict:'
new_method = '    def _walk_to(self, params: dict) -> dict:\n        x = params.get("x", 0)\n        z = params.get("z", 0)\n        y = params.get("y")\n        ms = params.get("ms", 2000)\n        return self.bot.walk_to(x, z, y, ms)\n\n    def _wait(self, params: dict) -> dict:'
if old_end in c:
    c = c.replace(old_end, new_method)
    p.write_text(c, encoding="utf-8")
    print("Added _walk_to method")
# Fix rule planner
p2 = pathlib.Path(r"C:\Users\Administrator\Documents\Singularity\src\singularity\core\rule_planner.py")
c2 = p2.read_text(encoding="utf-8")
old2 = '{"type": "move_to", "parameters": {"x": tpos.get("x", 0), "z": tpos.get("z", 0)}},\n                        {"type": "wait", "parameters": {"ms": 1500}},'
new2 = '{"type": "walk_to", "parameters": {"x": tpos.get("x", 0), "z": tpos.get("z", 0), "ms": 1500}},'
if old2 in c2:
    c2 = c2.replace(old2, new2)
    p2.write_text(c2, encoding="utf-8")
    print("Fixed rule planner to use walk_to")
else:
    print("pattern not found in rule planner")
    # debug
    idx = c2.find('"wait", "parameters": {"ms": 1500}')
    if idx > 0:
        print(f"Found at {idx}: {c2[idx-80:idx+80]}")

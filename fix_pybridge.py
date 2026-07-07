import pathlib
p = pathlib.Path(r"C:\Users\Administrator\Documents\Singularity\src\singularity\bot\bridge.py")
c = p.read_text(encoding="utf-8")
old = "    def move_to(self, x: float, z: float, y: float = None) -> dict:\n        return self._send_command_single(\"move_to\", {\"x\": x, \"z\": z, \"y\": y})"
new = '''    def walk_to(self, x: float, z: float, y: float = None, ms: int = 2000) -> dict:
        return self._send_command_single("walk_to", {"x": x, "z": z, "y": y, "ms": ms})

    def move_to(self, x: float, z: float, y: float = None) -> dict:
        return self._send_command_single("move_to", {"x": x, "z": z, "y": y})'''
if old in c:
    c = c.replace(old, new)
    p.write_text(c, encoding="utf-8")
    print("Fixed! Added walk_to")
else:
    print("ERROR: pattern not found")

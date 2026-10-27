"""Talk to a running Blender through the Blender MCP add-on (ahujasid/blender-mcp).

The add-on listens on localhost:9876 once you press "Connect to Claude" in Blender's sidebar (N
panel > BlenderMCP). This sends it the same JSON commands the MCP server does:

    python tools/blender_mcp.py info                      # scene summary
    python tools/blender_mcp.py run path/to/script.py     # run Python inside Blender, print result
    python tools/blender_mcp.py shot out.png [max_size]   # viewport screenshot
    python tools/blender_mcp.py cmd <type> '<json params>'

Scripts run with `bpy` available; set a variable named `result` to send a value back.
"""
import json
import socket
import sys

HOST, PORT = "127.0.0.1", 9876


def send(kind, params=None, timeout=600):
    with socket.create_connection((HOST, PORT), timeout=timeout) as s:
        s.sendall(json.dumps({"type": kind, "params": params or {}}).encode("utf-8"))
        buf = b""
        while True:
            chunk = s.recv(1 << 16)
            if not chunk:
                break
            buf += chunk
            try:
                return json.loads(buf.decode("utf-8"))
            except json.JSONDecodeError:
                continue
    return json.loads(buf.decode("utf-8"))


def main(argv):
    if not argv or argv[0] == "info":
        out = send("get_scene_info")
    elif argv[0] == "run":
        # Scripts can find their own folder (and the project) through __file__, as if run normally.
        import os
        path = os.path.abspath(argv[1])
        code = f"__file__ = {path!r}\n" + open(path, encoding="utf-8").read()
        out = send("execute_code", {"code": code})
    elif argv[0] == "shot":
        out = send("get_viewport_screenshot", {"filepath": argv[1], "max_size": int(argv[2]) if len(argv) > 2 else 1200, "format": "png"})
    elif argv[0] == "cmd":
        out = send(argv[1], json.loads(argv[2]) if len(argv) > 2 else {})
    else:
        sys.exit(__doc__)
    print(json.dumps(out, indent=1)[:20000])
    if isinstance(out, dict) and out.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])

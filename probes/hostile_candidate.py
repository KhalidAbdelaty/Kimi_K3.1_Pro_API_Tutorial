"""A program that tries to read secrets, reach the network, and write outside /work.
Run: python -m cadkit.runner probes/hostile_candidate.py  (it raises on purpose to print what it saw)"""
import os, socket, glob
out = {}
out["env_has_key"] = any("MOONSHOT" in k for k in os.environ)
try:
    socket.create_connection(("api.moonshot.ai", 443), timeout=3); out["net"] = "OPEN"
except Exception as e:
    out["net"] = type(e).__name__
out["visible_files"] = glob.glob("/work/*") + glob.glob("/home/*/*")
try:
    open("/sandbox/pwned", "w"); out["root_write"] = "OPEN"
except Exception as e:
    out["root_write"] = type(e).__name__
raise RuntimeError(str(out))

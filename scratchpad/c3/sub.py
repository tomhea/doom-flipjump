"""sub.py FILE  < patch   -- patch: blocks '<<<<\nOLD\n====\nNEW\n>>>>' ; exact, unique, LF-preserving"""
import sys
from pathlib import Path
p = Path(sys.argv[1])
s = p.read_bytes().decode("utf-8")
pat = sys.stdin.buffer.read().decode("utf-8").replace("\r\n", "\n")
blocks = pat.split("<<<<\n")[1:]
for b in blocks:
    old, rest = b.split("\n====\n", 1)
    new = rest.rsplit("\n>>>>", 1)[0]
    n = s.count(old)
    assert n == 1, ("count %d for" % n, old[:200])
    s = s.replace(old, new, 1)
p.write_bytes(s.encode("utf-8"))
print("patched", p, len(blocks), "blocks")

"""a built game binary presents its frames: menu, esc into the world, a few forward frames (run under `timeout`)"""
import sys
sys.path[:0] = ["src", "scratchpad/gp", "scratchpad"]
import probe as P
import gamespeed as GS
per_frame = [{}, {}, {"menu": ("esc",)}] + [{"forward": True}] * 5
r = P.GameBinary(sys.argv[1]).run(len(per_frame), GS.events_for(per_frame))
print("presented %d of %d frames, %d ops" % (len(r.frames), len(per_frame), r.ops))
sys.exit(0 if len(r.frames) == len(per_frame) else 1)

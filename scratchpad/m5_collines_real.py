"""M5a evidence — the upstream 0x0B decoder against the SHIPPED program's real byte stream.

tests/host/test_collines_device.py proves the new decoder agrees with the lab one on synthetic
streams. This proves it on the only stream that matters: the one `build/doom_e1m1_loop.fjm`
actually emits, tapped byte for byte out of a real multi-frame run.

The tap is reshaped into what a STANDALONE build will emit, and only in ways that are mechanical
and asserted:
  * the extended 9-byte 0x01 loses its trailing `flush_mode` byte (stock `present.init_screen`);
  * the 0x10 STATE and 0x11 THINGS blocks are dropped (a standalone build has no host to echo to).
Every dropped span is asserted to start with the command byte it claims, so a mis-sliced tap
fails here rather than quietly producing a stream that "happens to decode".

    python scratchpad/m5_collines_real.py [--fjm build/doom_e1m1_loop.fjm] [--frames 3]
    python scratchpad/m5_collines_real.py --selftest    # R9: the negative control

R9 negative control (`--selftest`): the same real stream is replayed through a decoder whose DITTO
branch has been removed, and this script must REJECT it. A run that cannot fail proves nothing.
"""
import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from doomfj.fastrun import FjmRunner, _fjcore                                  # noqa: E402
from doomfj.config import Config                                               # noqa: E402
from doomfj.mapcompiler import bake_bsp                                        # noqa: E402
from doomfj.reference_model import (MONSTER_TYPES, VANISHABLE_TYPES,           # noqa: E402
                                    ReferenceModel, spawn_state)
from doomfj.things import baked_thing_mask, vanishable_slots                   # noqa: E402
from doomfj.fixedpoint import _signed                                          # noqa: E402
from doomfj.wad import WadFile                                                 # noqa: E402
from doomfj.wireformat import (encode_bindings, encode_feed, encode_things,    # noqa: E402
                               encode_visibility)
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen            # noqa: E402
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory   # noqa: E402
from flipjump.utils.exceptions import IOReadOnEOF                              # noqa: E402
from tests.fj.stream_screen import StreamScreen                                # noqa: E402

CMD_INIT, CMD_STATE, CMD_THINGS = 0x01, 0x10, 0x11
DITTO, END = 0xFE, 0xFF


class TapScreen(StreamScreen):
    """the lab decoder, plus a byte-for-byte tap of the program's output and the spans of it that
    a standalone build would never emit."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.tap = bytearray()
        self.host_only = []          # (start, end, why) spans to drop for the upstream replay
        self.frames = []

    def _handle_byte(self, byte):
        self.tap.append(byte)
        return super()._handle_byte(byte)

    def _execute_command(self, command, payload):
        end = len(self.tap)          # the command's last byte was just appended
        if command in (CMD_STATE, CMD_THINGS):
            self.host_only.append((end - 1 - len(payload), end, f"{command:#04x} host echo"))
        elif command == CMD_INIT:
            self.host_only.append((end - 1, end, "0x01 flush_mode extension"))
        return super()._execute_command(command, payload)

    def _present(self):
        super()._present()
        self.frames.append(bytes(self.pixel_indices))


def standalone_stream(tap: bytes, host_only) -> bytes:
    """the tap minus every host-only span, with each span's identity asserted first."""
    out, cut = bytearray(), 0
    for start, end, why in sorted(host_only):
        assert start >= cut, f"host-only spans overlap at {start} ({why})"
        if why.startswith("0x1"):
            assert tap[start] == int(why[:4], 16), f"span at {start} is {tap[start]:#04x}, not {why}"
        else:
            assert end - start == 1 and tap[start] == 0, f"flush_mode at {start} is {tap[start]:#04x}, not 0"
        out += tap[cut:start]
        cut = end
    out += tap[cut:]
    return bytes(out)


def _Recording(base):
    """`base` plus a snapshot of every PRESENTED frame -- a device's pixel buffer at the end of a
    stream is whatever the next frame's init_screen left there, not a frame."""

    class Recording(base):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.frames = []

        def _present(self):
            super()._present()
            self.frames.append(bytes(self.pixel_indices))

    return Recording


def feed(device, data: bytes):
    for byte in data:
        for i in range(8):
            device.write_bit(bool((byte >> i) & 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_loop.fjm")
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--frames", type=int, default=3)
    ap.add_argument("--selftest", action="store_true",
                    help="R9: replay through a decoder with the DITTO branch removed; must FAIL")
    args = ap.parse_args()

    w = WadFile.from_path(str(ROOT / args.wad))
    art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
    rm = ReferenceModel(Config())
    cmap = bake_bsp(w, "E1M1")
    drawable = [t for t in w.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
    baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
    nvis = len(vanishable_slots(drawable, baked, VANISHABLE_TYPES))
    runtime = [t for t, b in zip(drawable, baked) if not b]
    binds = encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in runtime])
    things = encode_things([(t.x << 16, t.y << 16) for t in runtime])
    vis = encode_visibility([1] * nvis)
    sp = spawn_state(w, "E1M1")
    px, py, pa = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16, sp.angle

    # a few DIFFERENT viewpoints, so the tap carries real run-lists and real dittos
    views = [(px, py, pa), (px + 48, py, (pa + 0x08000000) & 0xFFFFFFFF),
             (px, py + 48, (pa + 0x20000000) & 0xFFFFFFFF),
             (px - 32, py - 32, (pa + 0x40000000) & 0xFFFFFFFF)][:args.frames]
    blob = b"".join(encode_feed(vx << 16, vy << 16, va, 0) + things + binds + vis
                    for vx, vy, va in views)

    print(f"running {args.fjm} for {len(views)} frame(s)...", flush=True)
    runner = FjmRunner(ROOT / args.fjm)
    assert runner.native, "this needs the native engine"
    core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
    for seg, n in runner._segments:
        core.add_segment(seg, n)
    for start, vals in runner._runs:
        core.set_words(start, vals)
    lab = TapScreen(stdin=blob, n_things=len(runtime))
    lab.attach_memory(NativeDeviceMemory(core, runner.width))
    _c, ops, _e, _l, _p = core.run(lab.read_bit, lab.write_bit, IOReadOnEOF, last_ops_length=0)
    tap, host_only, lab_frames = bytes(lab.tap), list(lab.host_only), list(lab.frames)
    # the core stays alive: `set_palette` (0x02) is a DMA read, so the upstream replay needs the
    # SAME memory the run left behind -- the palette is static data the reset restores, so this is
    # the image a standalone build would present from.
    memory = NativeDeviceMemory(core, runner.width)
    print(f"  {ops:,} ops -> {len(lab_frames)} frame(s), {len(tap):,} output bytes")
    assert len(lab_frames) == len(views), f"{len(lab_frames)} frames presented, want {len(views)}"

    stream = standalone_stream(tap, host_only)
    dropped = len(tap) - len(stream)
    print(f"  standalone-shaped stream: {len(stream):,} bytes ({dropped:,} host-only bytes dropped"
          f" over {len(host_only)} spans)")
    assert stream[0] == CMD_INIT and len(stream) < len(tap)

    if args.selftest:
        original = InMemoryScreen._handle_collines_byte

        def broken(self, byte):                       # the DITTO branch, removed
            if self._collines_column is not None and self._collines_y2 is None and byte == DITTO:
                self._collines_column = None
                return
            return original(self, byte)
        InMemoryScreen._handle_collines_byte = broken

    # CONTROL: the LAB decoder on a stream reshaped the SAME way except for the flush bytes
    # (which it needs and upstream must not have). If this differs from the run's own frames, the
    # host-echo removal is what is wrong -- a different bug that looks identical in a pixel diff.
    control = _Recording(StreamScreen)(n_things=len(runtime))
    control.attach_memory(memory)
    feed(control, standalone_stream(tap, [h for h in host_only if h[2].startswith("0x1")]))
    ctl_ok = control.frames == lab_frames
    print(f"  CONTROL (lab decoder, host echoes dropped): "
          f"{'ok' if ctl_ok else 'THE ECHO REMOVAL IS WRONG'}  {len(control.frames)} frame(s)")

    upstream = _Recording(InMemoryScreen)()
    upstream.attach_memory(memory)
    feed(upstream, stream)

    print("")
    ok = ctl_ok and upstream.frame_count == len(lab_frames)
    print(f"  frame count: upstream {upstream.frame_count} vs lab {len(lab_frames)}"
          f"  {'ok' if upstream.frame_count == len(lab_frames) else 'MISMATCH'}")
    # every frame, snapshotted at PRESENT time -- reading pixel_indices at the end would compare
    # against whatever the NEXT frame's init_screen left there, not against a presented frame.
    for i, (up, lb) in enumerate(zip(upstream.frames, lab_frames)):
        same = up == lb
        ok = ok and same
        note = "BYTE-EXACT" if same else f"DIFFER ({sum(1 for x, y in zip(up, lb) if x != y):,} px)"
        print(f"  frame {i}: upstream {hashlib.sha256(up).hexdigest()[:16]}"
              f"  lab {hashlib.sha256(lb).hexdigest()[:16]}  {note}")

    print("")
    if args.selftest:
        print("SELFTEST (ditto branch removed): "
              + ("FAIL -- the check did not notice a broken decoder" if ok
                 else "PASS -- the check rejected it"))
        return 0 if not ok else 1
    print("M5a REAL-STREAM CHECK: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""M12k (F4) — isolated unit tests for the packed-byte framebuffer store macros (src/fj/framebuffer.fj).
The framebuffer's only observable channel is the screen device (it DMA-reads the W*H packed bytes on a
0x03 present), so we write pixels with the macro under test, present once through InMemoryScreen, and
assert the captured `pixel_indices` byte-exact. Stores are fixed-address XOR-into-zero-init writes (D2b),
so there is no precondition/@Assumes to fail — only sanity + edge (corner pixels, a single column,
independence of distinct pixels) per the test mandate."""
from pathlib import Path

import flipjump as fj
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen

from doomfj.config import Config
from doomfj.harness import W
from doomfj.texturecompiler import compile_palette
from doomfj.wad import WadFile

FB_FJ = Path("src/fj/framebuffer.fj")
PRESENT_FJ = Path("src/fj/present.fj")
ASSET = "tests/fixtures/freedoom_assets.wad"


def _present(tmp_path, name, stores):
    """Assemble a program that runs `stores` (fb.* calls) then presents the framebuffer once; return the
    device's pixel_indices (a flat W*H list of palette indices)."""
    cfg = Config()
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    palette = compile_palette("palette", WadFile.from_path(ASSET))
    prog = "\n".join([
        "stl.startup_and_init_all",
        "present.init_screen",
        *stores,
        "present.set_palette palette",
        "present.update_screen framebuffer",
        "stl.loop",
        f"framebuffer: hex.vec {cfg.FB_SIZE}",
        palette,
    ])
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    out = tmp_path / f"{name}.fjm"
    fj.assemble([consts.resolve(), PRESENT_FJ.resolve(), FB_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)
    screen = InMemoryScreen()
    fj.run(out, io_device=screen, print_time=False, print_termination=False)
    return list(screen.pixel_indices)


def test_store_single_pixel(tmp_path):
    """fb.store sets exactly one packed byte (row-major index k) to a constant; the rest stay zero-init."""
    cfg = Config()
    k, color = 5 * cfg.VIEW_W + 7, 0x2A             # pixel (x=7, row=5)
    px = _present(tmp_path, "store_one", [f"fb.store framebuffer, {k}, {color}"])
    assert len(px) == cfg.FB_SIZE
    assert px[k] == color
    assert all(px[i] == 0 for i in range(cfg.FB_SIZE) if i != k)


def test_store_corners_independent(tmp_path):
    """The first and last pixels are stored independently (distinct addresses, no interference)."""
    cfg = Config()
    last = cfg.FB_SIZE - 1
    px = _present(tmp_path, "store_corners",
                  [f"fb.store framebuffer, 0, {0x11}", f"fb.store framebuffer, {last}, {0x99}"])
    assert px[0] == 0x11 and px[last] == 0x99
    assert all(px[i] == 0 for i in range(1, last))


def test_fill_column(tmp_path):
    """fb.fill_column sets every one of the H rows of column x to the colour, and nothing else."""
    cfg = Config()
    x, color = 3, 0x40
    px = _present(tmp_path, "fill_col", [f"fb.fill_column framebuffer, {x}, {color}"])
    for row in range(cfg.VIEW_H):
        assert px[row * cfg.VIEW_W + x] == color
    assert sum(1 for v in px if v == color) == cfg.VIEW_H        # exactly H pixels set


def test_clear_sets_every_pixel(tmp_path):
    """fb.clear writes the colour into every packed byte (W*H fixed stores from the zero-init)."""
    cfg = Config()
    color = 0x7C
    px = _present(tmp_path, "clear", [f"fb.clear framebuffer, {color}"])
    assert all(v == color for v in px)

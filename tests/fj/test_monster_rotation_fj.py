"""M7 P3.1: the monster rotation leaf (monstercode.rotation_leaf_lines + mrot) on the real flipjump engine against
the ONE rule, doomfj.monsters.rotation: a viewer with fractional 16.16 coordinates, things around it in every
octant and on the axes and diagonals, every facing. R9: a mutated mrot entry must fail."""
import random
from pathlib import Path

import flipjump as fj

from doomfj import monstercode as MC
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj, generate_tantoangle_lut_fj
from doomfj.monsters import rotation
from doomfj.reference_model import SLOPERANGE, ReferenceModel
from doomfj.tables import slopediv_recip8_table, tantoangle_table
from doomfj.wall_renderer import hoisted_scratch_fj

FJ = Path(__file__).resolve().parents[2] / "src" / "fj"


def _cases():
    rnd = random.Random(0x31)
    views = [(0, 0), (1056 << 16 | 0x8000, (-3616 << 16) + 0x4321), (-512 << 16, 700 << 16 | 0x1)]
    offs = [(100, 0), (0, 100), (-100, 0), (0, -100), (64, 64), (-64, 64), (64, -64), (-64, -64),
            (100, 3), (3, 100), (-100, -3), (1, 0), (0, 1), (0, 0)]
    offs += [(rnd.randint(-900, 900), rnd.randint(-900, 900)) for _ in range(20)]
    out = []
    for vx, vy in views:
        for dx, dy in offs:
            tx, ty = ((vx >> 16) + dx) << 16, ((vy >> 16) + dy) << 16
            out.append((vx, vy, tx, ty, rnd.randrange(8)))
    return out


def _run(tmp_path, name, table_values) -> bool:
    rm = ReferenceModel()
    cases = _cases()
    body, data = ["stl.startup_and_init_all"], []
    for k, (vx, vy, tx, ty, f) in enumerate(cases):
        body += ["hex.mov 8, viewx, vx%d" % k, "hex.mov 8, viewy, vy%d" % k, "hex.mov 8, mr_tx, tx%d" % k,
                 "hex.mov 8, mr_ty, ty%d" % k, "hex.set 1, mr_face, %d" % f,
                 "stl.fcall mon_rot_leaf, mr_ret", "hex.print_as_digit 1, mr_rot, 0"]
        data += ["vx%d: hex.vec 8, %d" % (k, vx & 0xFFFFFFFF), "vy%d: hex.vec 8, %d" % (k, vy & 0xFFFFFFFF),
                 "tx%d: hex.vec 8, %d" % (k, tx & 0xFFFFFFFF), "ty%d: hex.vec 8, %d" % (k, ty & 0xFFFFFFFF)]
    body += ["stl.output 10", "stl.loop"]
    data += ["viewx: hex.vec 8", "viewy: hex.vec 8"] + MC.ROT_DECLS + MC.rotation_leaf_lines(1)
    data += [generate_dispatch_table_fj("mrot", table_values, index_nibbles=2, result_nibbles=1),
             generate_dispatch_table_fj("ttang", tantoangle_table(SLOPERANGE), index_nibbles=3, result_nibbles=8),
             generate_dispatch_table_fj("sdrecip", slopediv_recip8_table(), index_nibbles=3, result_nibbles=6),
             generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)]
    expected = ("".join("%x" % (rotation(rm, vx, vy, tx, ty, f) - 1) for vx, vy, tx, ty, f in cases) + "\n").encode()
    prog = "\n".join(body + data) + "\n" + hoisted_scratch_fj()
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "projection.fj").resolve(),
            (FJ / "frame_render.fj").resolve(), p.resolve()]
    return fj.assemble_and_run_test_output(srcs, b"", expected, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_rotation_leaf_is_r_projectsprites(tmp_path):
    assert _run(tmp_path, "mrot", MC.rot_table_values()), "the fj rotation parted from doomfj.monsters.rotation"


def test_control_a_mutated_rotation_entry_is_caught(tmp_path):
    vals = MC.rot_table_values()
    rm = ReferenceModel()
    # mutate the entry the FIRST case reads, so the control is not vacuous by construction
    vx, vy, tx, ty, f = _cases()[0]
    n = rm.point_to_angle(vx, vy, tx, ty) >> 28
    vals[(n << 4) | f] ^= 1
    assert not _run(tmp_path, "mrot_mut", vals), "a mutated mrot entry passed: the comparison is vacuous"

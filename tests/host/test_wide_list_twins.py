"""M8 F1.5 (docs/f1-runtime-ids.md, option A1) -- the WIDE list macros are TWINS of the 8-bit ones, by rule.

A wide-list map (Config.LIST_ID_BITS = 12) calls `sim.leaf_link_w` / `sim.leaf_unlink_w` / `sim.thing_pass_depth_w` /
`sim.rank_key_w`: the same ops as the 8-bit macros but for the list cell's accessor (hex.read_cell / hex.write_cell,
flipjump's dual decoder table) and the id's width (3 nibbles where the 8-bit macro has 2). The 8-bit macros are NOT
touched -- E1M1's and E1M2's programs, and every heat key that names their macro paths, stay what they were -- so the
two copies could drift. This test derives each wide body FROM the narrow one by the documented substitutions and
requires the file's wide body to equal it, ops only (comments and blank lines dropped).

R9: the CONTROL perturbs the file's wide body (an accessor left narrow, a width left 2, an op dropped, a branch swapped)
and requires the derivation check to reject each.
"""
import re
from pathlib import Path

import pytest

SIM = Path(__file__).resolve().parents[2] / "src" / "fj" / "sim.fj"
SIM_WIDE = Path(__file__).resolve().parents[2] / "src" / "fj" / "sim_wide.fj"     # the twins' own file
GUARD = "rep(hex.pointers.PTR_WIDE_BITS != 12, i) .LIST_WIDE__needs__D_hex_pointers_PTR_WIDE_BITS_12"


def macro(text: str, name: str, nparams: int) -> list:
    """the op lines (comments stripped, blank lines dropped, whitespace normalised) of `def name` with `nparams`
    parameters, its header included"""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        m = re.match(r"\s*def (\S+)(.*)$", ln)
        if not m or m.group(1) != name:
            continue
        head = [ln]
        j = i
        while not lines[j].rstrip().endswith("{"):
            j += 1
            head.append(lines[j])
        params = " ".join(head).split("{")[0]
        params = re.sub(r"\s+", " ", params.replace("\\", " ")).strip()
        plist = params.split(" ", 2)[2] if params.count(" ") >= 2 else ""
        plist = re.split(r"[@<>]", plist)[0]
        n = len([p for p in plist.split(",") if p.strip()])
        if n != nparams:
            continue
        body = []
        k = j + 1
        while lines[k].rstrip() != "    }":
            body.append(lines[k])
            k += 1
        out = [re.sub(r"\s+", " ", params).strip()]
        for b in body:
            b = b.split("//")[0].strip()
            if b:
                out.append(re.sub(r"\s+", " ", b))
        return out
    raise KeyError("%s/%d not in sim.fj" % (name, nparams))


def _ids3(ln: str) -> str:
    return re.sub(r"(hex\.(?:mov|inc|if0|cmp|zero)) 2, ll_", r"\1 3, ll_", ln)


RULES = {
    # (narrow name, params): (wide name, a line rewrite)
    ("sim.leaf_link", 2): ("sim.leaf_link_w", lambda ln: _ids3(ln.replace("hex.read_byte ", "hex.read_cell ")
                                                               .replace("hex.write_byte ", "hex.write_cell "))),
    ("sim.leaf_unlink", 2): ("sim.leaf_unlink_w", lambda ln: _ids3(ln.replace("hex.read_byte ", "hex.read_cell ")
                                                                   .replace("hex.write_byte ", "hex.write_cell "))),
    ("sim.thing_pass_depth", 9): ("sim.thing_pass_depth_w",
                                  lambda ln: (ln.replace("hex.read_byte ", "hex.read_cell ")
                                              .replace("hex.set 2, td_rk, rk0", "hex.set 3, td_rk, rk0")
                                              .replace(".rank_key", ".rank_key_w"))),
    ("sim.thing_pass_depth", 7): ("sim.thing_pass_depth_w", lambda ln: ln.replace(".thing_pass_depth ",
                                                                                   ".thing_pass_depth_w ")),
    ("sim.rank_key", 0): ("sim.rank_key_w", lambda ln: ln.replace("hex.cmp 2, td_t, td_rk", "hex.cmp 3, td_t, td_rk")),
}


def derived(text: str, narrow: str, nparams: int) -> list:
    wide, rule = RULES[(narrow, nparams)]
    short_n, short_w = narrow.split(".")[1], wide.split(".")[1]
    lines = macro(text, short_n, nparams)
    return [lines[0].replace("def %s " % short_n, "def %s " % short_w, 1)] + [rule(ln) for ln in lines[1:]]


def actual(text: str, narrow: str, nparams: int) -> list:
    wide = RULES[(narrow, nparams)][0].split(".")[1]
    lines = macro(text, wide, nparams)
    # the wide macros that read or write a list cell open with the guard: no dual table, no assembly
    return [ln for ln in lines if ln != GUARD]


def check(text: str, wide: str) -> list:
    """[(macro, first differing line)] -- empty when every wide twin (in `wide`, sim_wide.fj) is its narrow macro (in
    `text`, sim.fj) under RULES"""
    bad = []
    for (narrow, n) in RULES:
        d, a = derived(text, narrow, n), actual(wide, narrow, n)
        if d != a:
            k = next((i for i, (x, y) in enumerate(zip(d, a)) if x != y), min(len(d), len(a)))
            bad.append(("%s/%d" % (narrow, n), d[k] if k < len(d) else None, a[k] if k < len(a) else None))
    return bad


def test_every_wide_twin_is_its_narrow_macro_by_rule():
    text, wide = SIM.read_text(encoding="utf-8"), SIM_WIDE.read_text(encoding="utf-8")
    assert check(text, wide) == []
    # the guard is where the rule says: each wide macro that touches a list cell opens with it
    for name, n in (("leaf_link_w", 2), ("leaf_unlink_w", 2), ("thing_pass_depth_w", 9)):
        assert macro(wide, name, n)[1] == GUARD, name
    # and the 8-bit file holds no twin: the 8-bit programs never see them
    assert "_w " not in "".join(ln for ln in text.split("\n") if ln.lstrip().startswith("def "))


def test_the_rules_change_what_they_say():
    """the derivation is not vacuous: the rules rewrite the accessors and the widths they name, and nothing else"""
    text = SIM.read_text(encoding="utf-8")
    for key, want in ((("sim.leaf_link", 2), 14), (("sim.leaf_unlink", 2), 17), (("sim.thing_pass_depth", 9), 5)):
        n = sum(a != b for a, b in zip(macro(text, key[0].split(".")[1], key[1])[1:], derived(text, *key)[1:]))
        assert n == want, (key, n)


@pytest.mark.parametrize("name,old,new", [
    ("an accessor left narrow", "        hex.read_cell td_head, td_p\n", "        hex.read_byte td_head, td_p\n"),
    ("a width left 2", "        hex.cmp 3, ll_v, ll_enc, walk, head, walk\n", "        hex.cmp 2, ll_v, ll_enc, walk, head, walk\n"),
    ("an op dropped", "        hex.zero 3, ll_nxt\n        hex.write_cell ll_q, ll_nxt\n      done:\n",
     "        hex.write_cell ll_q, ll_nxt\n      done:\n"),
    ("a branch swapped", "        hex.cmp 4, mt_d, td_bk, take, next, next\n", "        hex.cmp 4, mt_d, td_bk, next, take, next\n"),
    ("the rank left 2 nibbles", "        hex.cmp 3, td_t, td_rk, r1, r0, r0\n", "        hex.cmp 2, td_t, td_rk, r1, r0, r0\n"),
])
def test_a_drifted_twin_is_caught(name, old, new):
    """R9: each mutation of the WIDE file must be rejected"""
    text, wide = SIM.read_text(encoding="utf-8"), SIM_WIDE.read_text(encoding="utf-8")
    assert wide.count(old) == 1, "%s: the mutation no longer matches src/fj/sim_wide.fj" % name
    assert check(text, wide.replace(old, new)) != [], name

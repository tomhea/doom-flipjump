"""The block pool of a blocked build, as the assembler laid it out, and its source words.

GROUPS. flipjump-151's BlockPool (flipjump/assembler/preprocessor.py) groups tables by the
EXPRESSION of the word they dispatch through (`str(src + w)`, e.g. "(hex.tables.res + 32)"); the
word is the source cell's JUMP word. `reconstruct()` re-runs BlockPool._preallocate from the frozen
counts cache and the build's knobs -- deterministic, which is what lets a build's two assemblies
agree -- so every group's block base and size are known without re-assembling. `eval_key()`
resolves a group expression against a label table (bit addresses). A PINNED word rests at
`base + value*dw` (assembler.BinaryData.insert_fj_op), so the base is read straight off the image.
"""
import gzip
import json
import re

from flipjump.assembler.preprocessor import BlockPool

W = 32
# ship-gate 1b's knobs (docs/ship-gate.md): the ones that enter _block_bits / _preallocate
KNOBS = {"pool_base": 0x60000000, "span_bits": 0x9fffffe0, "spread": 2, "spread_min_count": 256,
         "max_slot_ops": 512, "width_buckets": True}


def _tokens(key):
    out = []
    for raw in key.split(" "):
        i = 0
        while i < len(raw) and raw[i] == "(":
            out.append("(")
            i += 1
        j, closes = len(raw), 0
        while j > i and raw[j - 1] == ")":      # a label ends with its local name, never with ')'
            j -= 1
            closes += 1
        if raw[i:j]:
            out.append(raw[i:j])
        out.extend([")"] * closes)
    return out


def eval_key(key, labels_bits):
    """bit address of a group's source word, or None when a label does not resolve"""
    toks = _tokens(key)
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None

    def take():
        t = toks[pos[0]]
        pos[0] += 1
        return t

    def atom():
        t = take()
        if t == "(":
            v = expr()
            if take() != ")":
                raise ValueError("unbalanced: %s" % key)
            return v
        if re.fullmatch(r"-?\d+", t):
            return int(t)
        if t not in labels_bits:
            raise KeyError(t)
        return labels_bits[t]

    def total():
        v = atom()
        while peek() == "+":
            take()
            v += atom()
        return v

    def expr():
        v = total()
        if peek() == "?":
            take()
            a = expr()
            if take() != ":":
                raise ValueError("bad ternary: %s" % key)
            b = expr()
            return a if v else b
        return v

    try:
        v = expr()
    except KeyError:
        return None
    if pos[0] != len(toks):
        raise ValueError("trailing tokens in %s" % key)
    return v


def load_counts(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        blob = json.load(fh)
    return {"sig": blob.get("sig"), "counts": blob["counts"],
            "widths": {g: int(x) for g, x in blob["widths"].items()},
            "width_hist": {g: {int(k): int(v) for k, v in h.items()} for g, h in blob["width_hist"].items()},
            "alias": blob.get("alias") or {}}


def reconstruct(counts_path, knobs=None):
    """(BlockPool with every block placed, frozen counts) -- the build's layout, from its counts"""
    k = dict(KNOBS)
    k.update(knobs or {})
    fr = load_counts(counts_path)
    pool = BlockPool(W, k["pool_base"], counts=fr["counts"], widths=fr["widths"], span_bits=k["span_bits"],
                     alias=fr["alias"], spread=k["spread"], spread_min_count=k["spread_min_count"],
                     max_slot_ops=k["max_slot_ops"], width_hist=fr["width_hist"], width_buckets=k["width_buckets"])
    return pool, fr


def rest_base(image, jw_bits, pool_base_bits=KNOBS["pool_base"]):
    """the block base baked into a source word at rest, 0 when it carries none. A hex cell rests at
    value*dw <= 960 < 1024 bits and a block is aligned to >= 1024 bits, so the base is the rest."""
    v = image.word(jw_bits // W)
    if v is None:
        return None
    base = v & ~1023
    return base if base >= pool_base_bits else 0

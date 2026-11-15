"""Audit the generated pies widget INDEPENDENTLY of make_pies.py: parse the HTML back and re-derive its numbers.

    python audit_pies.py <pies.html> <classified.json> <games .runs.json> <calibration .runs.json> <game .fjm>
        every check, PASS / FAIL; exit 1 on any FAIL
    python audit_pies.py --selftest <the same five>
        R9: mutations of the widget, each must be caught
PALETTE_VALIDATOR names validate_palette.js, the palette validator of Claude Code's dataviz skill (node runs it).

Checks, for each pie: its rows parse and sum to its total (ops = gamespeed's game-only mean, size = the fjm's stored
words); each row equals the classified categories grouped (to the unit, after rounding); its percent and legend
strings and the numbers in its description equal values recomputed here; the order is by value; the aria-label and
the fallback text list the same slices with the same numbers; the centre shows the total. For both: the sr heading
carries both totals, slice counts and leading shares; one color per key, the same key in both pies; every key used
has a color; no check of the validator FAILs on a pie's real color sequence (wrap pair included) in either mode, the
chroma check on the lookup tables' grey aside (a WARN passes).
Not audited: the widget's script that paints the rows (the legend's template, the chart's data binding)."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

V = os.environ["PALETTE_VALIDATOR"]
GROUP = {"Frame reset, input, view": ["Frame reset", "Input and move", "View"],
         "Frame reset, input, view, startup": ["Frame reset", "Input and move", "View", "Startup"],
         "Game logic, status bar and menus": ["Game logic", "Status bar and menus"]}
CANVAS = {"ops": "opsPie", "size": "sizePie"}
NUMBER = re.compile(r"\d[\d,.]*[MK]?")


class Audit:
    """the checks made so far, each a PASS or a FAIL line"""

    def __init__(self):
        self.fails, self.notes = [], []

    def ck(self, ok, what):
        (self.notes if ok else self.fails).append(("PASS " if ok else "FAIL ") + what)


def short(v):
    return "%.2fM" % (v / 1e6) if v >= 1e6 else ("%.0fK" % (v / 1e3) if v >= 1e5 else "%.1fK" % (v / 1e3))


def members(label):
    """the classified categories a row's label stands for"""
    base = label.replace("Render: ", "")
    return GROUP.get(label, [base[0].upper() + base[1:]])


def parse_rows(html, name):
    """the rows of one pie: [key, label, value, description, percent, legend value]; None if they do not parse"""
    m = re.search(name + r": \{ unit: '(\w+)', rows: \[(.*?)\n  \]\}", html, re.S)
    if not m:
        return None
    return [json.loads("[" + r.strip().rstrip(",") + "]") for r in re.findall(r"^\s*\[(.*)\],?\s*$", m.group(2), re.M)]


def description_numbers(name, key, truth, borders):
    """the numbers a row's description must carry, in order"""
    if name == "ops":
        cats = {"game": ["Status bar and menus"], "reset": ["Frame reset", "Input and move", "View"]}.get(key, [])
        return [short(truth[c]) for c in cats]
    if key == "tables":
        pool = borders["pool_stored"]
        return [format(borders["pool_tables"], ","), short(pool), short(round(truth["Lookup tables"]) - pool)]
    if key == "sprites":
        return [short(borders["vpb"] - borders["sprite_bank"])]
    cats = {"game": ["Status bar and menus"], "reset": ["Startup", "View", "Frame reset", "Input and move"]}
    return [short(truth[c]) for c in cats.get(key, [])]


def check_rows(a, name, rows, truth, borders, total_want):
    vals = [r[2] for r in rows]
    tot = sum(vals)
    a.ck(tot == total_want, "%s sums to %d (got %d)" % (name, total_want, tot))
    a.ck(vals == sorted(vals, reverse=True), "%s sorted by value" % name)
    a.ck(len({r[0] for r in rows}) == len(rows), "%s one row per key" % name)
    for key, label, v, desc, p, legend in rows:
        want = sum(truth.get(c, 0) for c in members(label))
        a.ck(abs(v - want) <= 1, "%s %-30s %d == classified %.1f (+-1 rounding)" % (name, label, v, want))
        a.ck(p == "%.1f%%" % (100 * v / tot), "%s %s percent %s" % (name, label, p))
        a.ck(legend == short(v), "%s %s legend value %s" % (name, label, legend))
        a.ck(bool(desc.strip()), "%s %s has a description" % (name, label))
        numbers = [n.rstrip(",.") for n in NUMBER.findall(desc)]
        a.ck(numbers == description_numbers(name, key, truth, borders),
             "%s %s description numbers %s" % (name, label, numbers))


def check_canvas(a, html, name, rows):
    """the aria-label, the fallback text and the centre: the same slices, numbers and total as the rows"""
    m = re.search(r'id="%s" role="img" aria-label="([^"]*)">([^<]*)</canvas>' % CANVAS[name], html)
    a.ck(m is not None, "%s canvas aria + fallback parse" % name)
    if not m:
        return
    aria, fallback = m.group(1), m.group(2)
    parts = aria.split("sorted: ")[1].split(", ")
    a.ck(len(parts) == len(rows), "%s aria lists %d slices" % (name, len(rows)))
    for i, ((key, label, v, desc, p, legend), part) in enumerate(zip(rows, parts)):
        want = "%s %s%s" % (label.replace(":", "").replace(",", ""), p[:-1], " percent" if i == 0 else "")
        a.ck(part == want, "%s aria '%s' is '%s'" % (name, part, want))
    fparts = fallback.rstrip(".").split("; ")
    a.ck(len(fparts) == len(rows), "%s fallback lists %d slices" % (name, len(rows)))
    for (key, label, v, desc, p, legend), fp in zip(rows, fparts):
        a.ck(fp == "%s %s" % (label, format(v, ",")), "%s fallback '%s'" % (name, fp))
    mtot = "%.1f" % (sum(r[2] for r in rows) / 1e6)
    a.ck(("%s million" % mtot) in aria and ('<b>%sM</b>' % mtot) in html, "%s center + aria total %sM" % (name, mtot))


def check_heading(a, html, ops_rows, size_rows):
    """the screen-reader heading: both totals, both slice counts, both leading shares"""
    sr = re.search(r'<h2 class="sr-only">(.*?)</h2>', html).group(1)
    want = ("FJ ops per mean game frame, %.1f million, in %d slices led by rendering walls at %s percent; program "
            "size, %.1f million memory words, in %d slices led by lookup tables at %s percent."
            % (sum(r[2] for r in ops_rows) / 1e6, len(ops_rows), ops_rows[0][4][:-1],
               sum(r[2] for r in size_rows) / 1e6, len(size_rows), size_rows[0][4][:-1]))
    a.ck(sr.endswith(want), "sr heading ends '%s'" % want)
    a.ck(ops_rows[0][1] == "Render: walls" and size_rows[0][1] == "Lookup tables", "sr heading: the leading slices")


def color_maps(html):
    """mode -> key -> color, from the widget's script"""
    m = re.search(r"\? \{(.*?)\}\n  : \{(.*?)\};", html, re.S)
    return {mode: dict(re.findall(r"(\w+): '(#[0-9a-f]{6})'", body)) for mode, body in (("dark", m.group(1)),
                                                                                         ("light", m.group(2)))}


def validator_verdicts(seq, mode):
    """check name -> (PASS / WARN / FAIL, its detail) for one color sequence"""
    args = ["node", V, ",".join(seq), "--mode", mode] + (["--surface", "#1a1a19"] if mode == "dark" else [])
    out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8").stdout
    lines = re.finditer(r"\[(PASS|FAIL|WARN)\]\s+(.+?)\s{2,}(.*)", out)
    return {m.group(2).strip(): (m.group(1), m.group(3)) for m in lines}


def check_colors(a, html, sets):
    cols = color_maps(html)
    keys = {r[0] for rows in sets.values() for r in rows}
    a.ck(keys <= set(cols["light"]) and keys <= set(cols["dark"]), "every key has a light and a dark color")
    a.ck(all(len(set(c.values())) == len(c) for c in cols.values()), "no two keys share a color")
    for name, rows in sets.items():
        for mode in ("light", "dark"):
            seq = [cols[mode][r[0]] for r in rows]
            st = validator_verdicts(seq + [seq[0]], mode)
            gray = cols[mode]["tables"]
            bad = [k for k, (v, det) in st.items() if v == "FAIL" and not (k.startswith("Chroma") and
                   set(re.findall(r"#[0-9a-f]{6}", det)) <= {gray})]
            a.ck(not bad and st.get("CVD separation", ("?",))[0] in ("PASS", "WARN"),
                 "validator %s %s: %s" % (name, mode, " ".join("%s=%s" % (k.split()[0], v[0]) for k, v in st.items())))


def audit(html, cls, game_only, stored):
    a = Audit()
    sets = {name: parse_rows(html, name) for name in ("ops", "size")}
    for name, rows in sets.items():
        a.ck(rows is not None, "%s rows parse" % name)
    if None in sets.values():
        return a.fails, a.notes
    d = json.loads(open(cls).read())
    truth = {"ops": dict(d["ops"]), "size": {c: v[0] + v[1] for c, v in d["size"].items()}}
    total_want = {"ops": round(game_only / 1000), "size": stored}
    for name, rows in sets.items():
        check_rows(a, name, rows, truth[name], d["borders"], total_want[name])
        check_canvas(a, html, name, rows)
    check_heading(a, html, sets["ops"], sets["size"])
    check_colors(a, html, sets)
    return a.fails, a.notes


def totals(games_runs, cal_runs, fjm):
    """(the game-only ops of gamespeed's ten games, the .fjm's stored words): the games profile's runs (calibration +
    10 games) minus 11 x the calibration run, and the segment table's data words -- each from its own source,
    independent of the classifier"""
    g = json.load(open(games_runs))["runs"]
    c = json.load(open(cal_runs))["runs"][0]["ops"]
    assert g[0]["name"] == "calibration" and g[0]["ops"] == c, (g[0], c)
    game_only = sum(r["ops"] for r in g) - 11 * c
    from flipjump.fjm.fjm_reader import read_fjm_header          # flipjump's own reader: it reads every .fjm version
    stored = sum(data_length for _start, _length, _data_start, data_length in read_fjm_header(Path(fjm)).segments)
    print("totals: game-only ops %s (per frame %.1f), stored words %s" % (format(game_only, ","), game_only / 1000,
                                                                          format(stored, ",")))
    return game_only, stored


def exchange_colors(html, key_a, key_b):
    """both color maps with two keys' colors exchanged"""
    def exchanged(m):
        line = m.group(0)
        ca, cb = (re.search(r"%s: '(#[0-9a-f]{6})'" % k, line).group(1) for k in (key_a, key_b))
        return line.replace(ca, "#tmp").replace(cb, ca).replace("#tmp", cb)
    return re.sub(r"\n  [?:] \{ walls: [^\n]*", exchanged, html)


MUTATIONS = {
    "a row value off by 1,000": lambda h: re.sub(
        r'("Render: sprites", )(\d+)', lambda m: m.group(1) + str(int(m.group(2)) + 1000), h, 1),
    "a percent string wrong": lambda h: re.sub(
        r'("Game logic, status bar and menus", \d+, "[^"]*", ")([\d.]+)%', lambda m: m.group(1) + "9.9%", h, 1),
    "a legend value wrong": lambda h: re.sub(
        r'("Render: walls", \d+, "[^"]*", "[^"]*", ")([^"]+)"', lambda m: m.group(1) + '9.99M"', h, 1),
    "a description number wrong": lambda h: re.sub(
        r"(the pictures )([\d.]+[MK])", lambda m: m.group(1) + "9.99M", h, 1),
    "an aria percent wrong": lambda h: re.sub(r"(Render sprites )([\d.]+)", lambda m: m.group(1) + "99.9", h, 1),
    "an aria percent with a digit more": lambda h: re.sub(
        r"(Render sprites )([\d.]+)", lambda m: m.group(1) + m.group(2) + "9", h, 1),
    "the fallback text cut short": lambda h: re.sub(r"(; [^;<]*)(\.</canvas>)", lambda m: m.group(2), h, 1),
    "a fallback number wrong": lambda h: re.sub(
        r"(>Render: walls )([\d,]+)(;)", lambda m: m.group(1) + "9,999" + m.group(3), h, 1),
    "the centre total wrong": lambda h: re.sub(r"<b>[\d.]+M</b>", "<b>99.9M</b>", h, 1),
    "the heading's ops total wrong": lambda h: re.sub(
        r"(game frame, )([\d.]+)( million, in)", lambda m: m.group(1) + "99.9" + m.group(3), h, 1),
    "the heading's size total wrong": lambda h: re.sub(
        r"(program size, )([\d.]+)( million memory words, in)", lambda m: m.group(1) + "99.9" + m.group(3), h, 1),
    "two rows out of order": lambda h: re.sub(
        r"(ops: \{ unit: 'ops', rows: \[\n)([^\n]*\n)([^\n]*\n)", lambda m: m.group(1) + m.group(3) + m.group(2), h, 1),
    "a size row value replaced": lambda h: re.sub(r'(\["bsp", "BSP walk", )(\d+)', lambda m: m.group(1) + "1", h, 1),
    # the LIGHT map's `game` takes the walls' color: two keys share one
    "two light colors the same": lambda h: re.sub(
        r"(\n  : \{ walls: '(#[0-9a-f]{6})'[^\n]*?game: ')(#[0-9a-f]{6})", lambda m: m.group(1) + m.group(2), h, 1),
    "two dark colors the same": lambda h: re.sub(
        r"(\n  \? \{ walls: '(#[0-9a-f]{6})'[^\n]*?game: ')(#[0-9a-f]{6})", lambda m: m.group(1) + m.group(2), h, 1),
    # sprites in the amber and collision in the orange-red: the orange-red then sits beside the BSP walk's green
    "sprites and collision exchange colors": lambda h: exchange_colors(h, "sprites", "coll"),
}


def selftest(html, cls, game_only, stored):
    f0, _ = audit(html, cls, game_only, stored)
    assert not f0, "the real page must pass before the self-test means anything: %s" % f0[:3]
    ok = True
    for what, mutate in MUTATIONS.items():
        mutant = mutate(html)
        assert mutant != html, "mutation '%s' did not apply" % what
        f, _ = audit(mutant, cls, game_only, stored)
        print("%-38s %s (%d fails, e.g. %s)" % (what, "CAUGHT" if f else "MISSED", len(f), f[0][:90] if f else "-"))
        ok &= bool(f)
    print("selftest", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    game_only, stored = totals(*argv[-3:])
    argv = argv[:-3]
    if argv[0] == "--selftest":
        return selftest(open(argv[1], encoding="utf-8").read(), argv[2], game_only, stored)
    fails, notes = audit(open(argv[0], encoding="utf-8").read(), argv[1], game_only, stored)
    for n in notes + fails:
        print(n)
    print("\n%d checks, %d FAIL" % (len(notes) + len(fails), len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

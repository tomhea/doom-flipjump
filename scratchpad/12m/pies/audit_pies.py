"""Audit the generated pies widget INDEPENDENTLY of make_pies.py: parse the HTML back and re-derive every number.

    python audit_pies.py <pies.html> <classified.json> <games .runs.json> <calibration .runs.json> <game .fjm>
        every check, PASS / FAIL; exit 1 on any FAIL
    python audit_pies.py --selftest <the same five>
        R9: five mutations of the widget, each must be caught
PALETTE_VALIDATOR names validate_palette.js, the palette validator of Claude Code's dataviz skill (node runs it).

Checks: rows parse; each pie sums to its total (ops = gamespeed's game-only mean, size = the fjm's stored words); the
rows equal the classified categories grouped (to the unit, after rounding); the percent and legend strings equal
values recomputed here; the order is by value; the aria-labels, fallback text and sr heading carry the same names and
numbers; one color per key, the same key in both pies; every key used has a color; the validator passes both pies'
real color sequences (wrap pair included) in both modes."""
import json
import os
import re
import subprocess
import sys

V = os.environ["PALETTE_VALIDATOR"]
GAME_ONLY = STORED = None                           # set in main() from the runs.json files and the .fjm
GROUP = {"Frame reset, input, view": ["Frame reset", "Input and move", "View", "Startup"],
         "Game logic, status bar and menus": ["Game logic", "Status bar and menus"]}


def audit(html, cls):
    fails, notes = [], []

    def ck(ok, what):
        (notes if ok else fails).append(("PASS " if ok else "FAIL ") + what)

    sets = {}
    for name in ("ops", "size"):
        m = re.search(name + r": \{ unit: '(\w+)', rows: \[(.*?)\n  \]\}", html, re.S)
        ck(m is not None, "%s rows parse" % name)
        if not m:
            return fails, notes
        rows = [json.loads("[" + r.strip().rstrip(",") + "]") for r in re.findall(r"^\s*\[(.*)\],?\s*$", m.group(2), re.M)]
        sets[name] = rows
    d = json.loads(open(cls).read())
    truth = {"ops": {c: v for c, v in d["ops"].items()}, "size": {c: v[0] + v[1] for c, v in d["size"].items()}}
    total_want = {"ops": round(GAME_ONLY / 1000), "size": STORED}
    for name, rows in sets.items():
        vals = [r[2] for r in rows]
        tot = sum(vals)
        ck(tot == total_want[name], "%s sums to %d (got %d)" % (name, total_want[name], tot))
        ck(vals == sorted(vals, reverse=True), "%s sorted by value" % name)
        ck(len({r[0] for r in rows}) == len(rows), "%s one row per key" % name)
        for key, label, v, desc, p, short in rows:
            base = label.replace("Render: ", "").replace("walls", "Walls").replace("sprites", "Sprites") \
                .replace("floors and ceilings", "Floors and ceilings").replace("BSP walk", "BSP walk")
            members = GROUP.get(label, [base])
            want = sum(truth[name].get(c, 0) for c in members)
            ck(abs(v - want) <= 1, "%s %-30s %d == classified %.1f (+-1 rounding)" % (name, label, v, want))
            ck(p == "%.1f%%" % (100 * v / tot), "%s %s percent %s" % (name, label, p))
            s = "%.2fM" % (v / 1e6) if v >= 1e6 else ("%.0fK" % (v / 1e3) if v >= 1e5 else "%.1fK" % (v / 1e3))
            ck(short == s, "%s %s legend value %s" % (name, label, short))
            ck(bool(desc.strip()), "%s %s has a description" % (name, label))
        # the aria-label: the same names, order and percents
        canvas = "opsPie" if name == "ops" else "sizePie"
        m = re.search(r'id="%s" role="img" aria-label="([^"]*)">([^<]*)</canvas>' % canvas, html)
        ck(m is not None, "%s canvas aria + fallback parse" % name)
        aria, fb = m.group(1), m.group(2)
        parts = aria.split("sorted: ")[1].split(", ")
        ck(len(parts) == len(rows), "%s aria lists %d slices" % (name, len(rows)))
        for (key, label, v, desc, p, short), part in zip(rows, parts):
            want = "%s %s" % (label.replace(":", "").replace(",", ""), p[:-1])
            ck(part.startswith(want), "%s aria '%s' starts '%s'" % (name, part, want))
        fparts = fb.rstrip(".").split("; ")
        for (key, label, v, desc, p, short), fp in zip(rows, fparts):
            ck(fp == "%s %s" % (label, format(v, ",")), "%s fallback '%s'" % (name, fp))
        mtot = "%.1f" % (tot / 1e6)
        ck(("%s million" % mtot) in aria and ('<b>%sM</b>' % mtot) in html, "%s center + aria total %sM" % (name, mtot))
    # the sr heading
    sr = re.search(r'<h2 class="sr-only">(.*?)</h2>', html).group(1)
    o, s = sets["ops"], sets["size"]
    ck("in %d slices led by rendering walls at %s percent" % (len(o), o[0][4][:-1]) in sr and o[0][1] == "Render: walls",
       "sr heading: ops slice count + lead")
    ck("in %d slices led by lookup tables at %s percent" % (len(s), s[0][4][:-1]) in sr and s[0][1] == "Lookup tables",
       "sr heading: size slice count + lead")
    # colors: one map, each pie's real sequence validated
    cols = {}
    for mode in ("dark", "light"):
        m = re.search(r"\? \{(.*?)\}\n  : \{(.*?)\};", html, re.S)
        body = m.group(1) if mode == "dark" else m.group(2)
        cols[mode] = dict(re.findall(r"(\w+): '(#[0-9a-f]{6})'", body))
    keys = {r[0] for r in o} | {r[0] for r in s}
    ck(keys <= set(cols["light"]) and keys <= set(cols["dark"]), "every key has a light and a dark color")
    ck(len(set(cols["light"].values())) == len(cols["light"]) and len(set(cols["dark"].values())) == len(cols["dark"]),
       "no two keys share a color")
    for name, rows in sets.items():
        for mode in ("light", "dark"):
            seq = [cols[mode][r[0]] for r in rows]
            seq = seq + [seq[0]]
            args = ["node", V, ",".join(seq), "--mode", mode] + (["--surface", "#1a1a19"] if mode == "dark" else [])
            out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8").stdout
            st = dict((mm.group(2).strip(), (mm.group(1), mm.group(3))) for mm in
                      re.finditer(r"\[(PASS|FAIL|WARN)\]\s+(.+?)\s{2,}(.*)", out))
            gray = cols[mode]["tables"]
            bad = [k for k, (v, det) in st.items() if v == "FAIL" and not (k.startswith("Chroma") and
                   set(re.findall(r"#[0-9a-f]{6}", det)) <= {gray})]
            ck(not bad and st.get("CVD separation", ("?",))[0] in ("PASS", "WARN"),
               "validator %s %s: %s" % (name, mode, " ".join("%s=%s" % (k.split()[0], v[0]) for k, v in st.items())))
    return fails, notes


def _totals(games_runs, cal_runs, fjm):
    """GAME_ONLY = the games profile's runs (calibration + 10 games) minus 11 x the calibration run; STORED = the .fjm's
    stored data words, read from its segment table -- each from its own source, independent of the classifier"""
    global GAME_ONLY, STORED
    g = json.load(open(games_runs))["runs"]
    c = json.load(open(cal_runs))["runs"][0]["ops"]
    assert g[0]["name"] == "calibration" and g[0]["ops"] == c, (g[0], c)
    GAME_ONLY = sum(r["ops"] for r in g) - 11 * c
    from pathlib import Path                         # flipjump's own header reader: it reads every .fjm version
    from flipjump.fjm.fjm_reader import read_fjm_header
    STORED = sum(data_length for _start, _length, _data_start, data_length in read_fjm_header(Path(fjm)).segments)
    print("totals: game-only ops %s (per frame %.1f), stored words %s" % (format(GAME_ONLY, ","), GAME_ONLY / 1000,
                                                                          format(STORED, ",")))


def main(argv):
    _totals(*argv[-3:])
    argv = argv[:-3]
    if argv[0] == "--selftest":
        html, cls = open(argv[1], encoding="utf-8").read(), argv[2]
        f0, _ = audit(html, cls)
        assert not f0, "the real page must pass before the self-test means anything: %s" % f0[:3]
        muts = {
            "a row value off by 1,000": lambda h: re.sub(r'("Render: sprites", )(\d+)', lambda m: m.group(1) + str(int(m.group(2)) + 1000), h, 1),
            "a percent string wrong": lambda h: re.sub(r'("Game logic, status bar and menus", \d+, "[^"]*", ")([\d.]+)%', lambda m: m.group(1) + "9.9%", h, 1),
            "an aria percent wrong": lambda h: re.sub(r"(Render sprites )([\d.]+)", lambda m: m.group(1) + "99.9", h, 1),
            # the LIGHT map's `game` takes the walls' color: two keys now share one
            "a key colored differently": lambda h: re.sub(r"(\n  : \{ walls: '(#[0-9a-f]{6})'[^\n]*?game: ')(#[0-9a-f]{6})",
                                                          lambda m: m.group(1) + m.group(2), h, 1),
            "a size row value replaced": lambda h: re.sub(r'(\["bsp", "BSP walk", )(\d+)', lambda m: m.group(1) + "1", h, 1),
        }
        ok = True
        for what, mut in muts.items():
            h2 = mut(html)
            assert h2 != html, "mutation '%s' did not apply" % what
            f, _ = audit(h2, cls)
            print("%-34s %s (%d fails, e.g. %s)" % (what, "CAUGHT" if f else "MISSED", len(f), f[0][:90] if f else "-"))
            ok &= bool(f)
        print("selftest", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    html, cls = open(argv[0], encoding="utf-8").read(), argv[1]
    fails, notes = audit(html, cls)
    for n in notes + fails:
        print(n)
    print("\n%d checks, %d FAIL" % (len(notes) + len(fails), len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
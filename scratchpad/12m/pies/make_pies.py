"""The two pies' widget, generated from classify.py's output: every number, percentage, label and aria string comes
from ONE computation here (nothing typed by hand).

    python make_pies.py <classified.json> <pies.html>        the widget
    python make_pies.py --page <pies.html> <page.html>       the widget as a whole light-mode page, drawn at once: the
                                                             page a browser screenshots into the README's picture
"""
import json
import math
import sys

PAGE_HEAD = """<!doctype html>
<html lang="en" data-mode="light"><head><meta charset="utf-8"><title>blocked65 pies</title>
<style>
:root{--text-primary:#1a1a19;--text-secondary:#4a4a47;--text-muted:#73726c;--surface-0:#ffffff}
html,body{margin:0;background:#ffffff}
body{font-family:"Segoe UI",system-ui,-apple-system,Helvetica,Arial,sans-serif;padding:20px 32px;box-sizing:border-box;width:1104px}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
</style></head><body>
"""
ANIMATED, STILL = "options: { responsive: true", "options: { animation: false, responsive: true"


def page(widget):
    """the widget as a whole page whose charts are drawn at once (a screenshot must not catch them mid-animation)"""
    assert widget.count(ANIMATED) == 1, widget.count(ANIMATED)
    return PAGE_HEAD + widget.replace(ANIMATED, STILL) + "\n</body></html>\n"


if sys.argv[1] == "--page":
    open(sys.argv[3], "w", encoding="utf-8", newline="\n").write(page(open(sys.argv[2], encoding="utf-8").read()))
    sys.exit(0)

d = json.load(open(sys.argv[1]))
size = {c: v[0] + v[1] for c, v in d["size"].items()}
ops = dict(d["ops"])

GROUPS = [  # key, ops name, size name, member categories
    ("walls", "Render: walls", "Walls", ["Walls"]),
    ("sprites", "Render: sprites", "Sprites", ["Sprites"]),
    ("bsp", "Render: BSP walk", "BSP walk", ["BSP walk"]),
    ("coll", "Collision and positions", "Collision and positions", ["Collision and positions"]),
    ("floors", "Render: floors and ceilings", "Floors and ceilings", ["Floors and ceilings"]),
    ("game", "Game logic, status bar and menus", "Game logic, status bar and menus", ["Game logic", "Status bar and menus"]),
    ("reset", "Frame reset, input, view", "Frame reset, input, view, startup",
     ["Frame reset", "Input and move", "View", "Startup"]),
    ("tables", None, "Lookup tables", ["Lookup tables"]),
]
covered = {c for g in GROUPS for c in g[3]}
assert covered == set(size) | set(ops), (covered ^ (set(size) | set(ops)))
assert abs(ops.get("Lookup tables", 0)) < 1e-9 and ops.get("Startup", 0) == 0     # no game-frame op is in either


def largest_remainder(vals, total):
    fl = {k: math.floor(v) for k, v in vals.items()}
    for k in sorted(vals, key=lambda k: -(vals[k] - fl[k]))[:round(total) - sum(fl.values())]:
        fl[k] += 1
    assert sum(fl.values()) == round(total)
    return fl


def pct(v, total):
    return "%.1f" % (100 * v / total)


def short(v):
    return "%.2fM" % (v / 1e6) if v >= 1e6 else ("%.0fK" % (v / 1e3) if v >= 1e5 else "%.1fK" % (v / 1e3))


og = {k: sum(ops.get(c, 0) for c in cs) for k, _o, _s, cs in GROUPS if _o}
sg = {k: sum(size.get(c, 0) for c in cs) for k, _o, _s, cs in GROUPS}
OT, ST = sum(ops.values()), sum(size.values())
oi, si = largest_remainder(og, OT), largest_remainder(sg, ST)
B = d["borders"]                                    # classify.py: every border from the build itself
PIC = B["vpb"] - B["sprite_bank"]                   # the sprite bank: the pictures
POOL = B["pool_stored"]                             # the table pool's stored words
rest_tables = round(sg["tables"]) - POOL
r_ops = {c: ops[c] for c in ("Frame reset", "Input and move", "View")}
r_size = {c: size[c] for c in ("View", "Frame reset", "Input and move", "Startup")}
ODESC = {
    "walls": "wall columns and step faces, and putting each screen column together",
    "sprites": "monsters, items, decorations, fireballs, the weapon in hand: projecting, depth sorting, their pieces in each column",
    "bsp": "walking the BSP tree front to back: which subsectors, walls and sprites are visible",
    "coll": "every move (player, monsters, knockback, projectiles) tested against walls and things; point location; where things are",
    "floors": "the floor and ceiling bands, and their parts of each column: which plane fills it, the floor and ceiling spliced around step faces",
    "game": "monsters, combat, weapons, doors, lifts, items, barrels; status bar, screen flashes, menu keys %s" % short(ops["Status bar and menus"]),
    "reset": "frame reset %s, input and move %s, view %s" % tuple(short(r_ops[c]) for c in ("Frame reset", "Input and move", "View")),
}
SDESC = {
    "tables": "%s tables in the pool (%s words); %s more: the table part's, the state part's and the runtime's, "
              "with their word-flip chains" % (format(B["pool_tables"], ","), short(POOL), short(rest_tables)),
    "coll": "collision cells and tests for every move; point-location trees; the thing lists",
    "floors": "the floor and ceiling rows compiled to code, their loaders, their parts of the column code, per-column plane cells",
    "game": "monsters, combat, weapons, doors, lifts, items, barrels, state cells; the menu, help and map screens and the status bar %s" % short(size["Status bar and menus"]),
    "sprites": "the pictures %s, the weapon-in-hand pictures, drawing code, per-sprite constants and cells" % short(PIC),
    "walls": "drawing code, per-seg constants, the step-face columns",
    "bsp": "the BSP tree and the per-subsector visits, compiled to code",
    "reset": "startup and the boot screen %s, view %s, frame reset %s, input and move %s" % tuple(short(r_size[c]) for c in ("Startup", "View", "Frame reset", "Input and move")),
}
names_o = {k: o for k, o, _s, _c in GROUPS if o}
names_s = {k: s for k, _o, s, _c in GROUPS}
orow = sorted(((k, names_o[k], oi[k], ODESC[k]) for k in oi), key=lambda r: -r[2])
srow = sorted(((k, names_s[k], si[k], SDESC[k]) for k in si), key=lambda r: -r[2])


def js_rows(rows, total):
    return ",\n    ".join("[%s, %s, %d, %s, %s, %s]" % (json.dumps(k), json.dumps(n), v, json.dumps(dsc), json.dumps(pct(v, total) + "%"),
                                                     json.dumps(short(v))) for k, n, v, dsc in rows)


def aria(rows, total):
    return ", ".join("%s %s%s" % (n.replace(":", "").replace(",", ""), pct(v, total), " percent" if i == 0 else "")
                     for i, (k, n, v, _d) in enumerate(rows))


def fallback(rows):
    return "; ".join("%s %s" % (n, format(v, ",")) for k, n, v, _d in rows) + "."


OTOT, STOT = round(OT), round(ST)
html = """<h2 class="sr-only">Two donut charts for the shipped binary blocked65, sorted by share, each part of the program in the same color in both: FJ ops per mean game frame, {otm} million, in {on} slices led by rendering walls at {ow} percent; program size, {stm} million memory words, in {sn} slices led by lookup tables at {sl} percent.</h2>
<style>
.pg{{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:28px;padding:0.5rem 0 0.25rem}}
.lab{{font-size:16px;font-weight:500;color:var(--text-primary);margin:0 0 10px}}
.wrap{{position:relative;height:250px}}
.ctr{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;pointer-events:none}}
.ctr b{{font-size:20px;font-weight:500;color:var(--text-primary);font-variant-numeric:tabular-nums}}
.ctr span{{font-size:12px;color:var(--text-muted)}}
.lg{{list-style:none;margin:12px 0 0;padding:0;font-size:13px}}
.lg li{{display:grid;grid-template-columns:12px minmax(0,1fr) auto 50px;gap:8px;align-items:center;padding:2px 0;color:var(--text-secondary);font-variant-numeric:tabular-nums}}
.lg i{{width:10px;height:10px;border-radius:2px;display:block}}
.lg .v{{color:var(--text-primary);text-align:right}}
.lg .p{{text-align:right}}
</style>
<div class="pg">
  <div>
    <p class="lab">FJ ops per mean frame</p>
    <div class="wrap"><canvas id="opsPie" role="img" aria-label="Donut chart of FJ ops per mean game frame, {otm} million, sorted: {oaria}">{ofb}</canvas><div class="ctr"><b>{otm}M</b><span>FJ ops</span></div></div>
    <ul class="lg" id="opsLg"></ul>
  </div>
  <div>
    <p class="lab">Program size</p>
    <div class="wrap"><canvas id="sizePie" role="img" aria-label="Donut chart of program size, {stm} million memory words, sorted: {saria}">{sfb}</canvas><div class="ctr"><b>{stm}M</b><span>memory words</span></div></div>
    <ul class="lg" id="sizeLg"></ul>
  </div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
const mode = document.documentElement.dataset.mode;
const dark = mode ? mode === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
// one color per part of the program, the same in both charts (every neighbour pair and the wrap validated, both modes)
const COL = dark
  ? {{ walls: '#3987e5', sprites: '#d95926', bsp: '#008300', coll: '#c98500', floors: '#9085e9', game: '#199e70', reset: '#e66767', tables: '#65635e' }}
  : {{ walls: '#2a78d6', sprites: '#eb6834', bsp: '#008300', coll: '#eda100', floors: '#4a3aa7', game: '#1baf7a', reset: '#e34948', tables: '#7d7c78' }};
const css = getComputedStyle(document.documentElement);
const gap = (css.getPropertyValue('--surface-0') || '').trim() || (dark ? '#1a1a19' : '#ffffff');
const nf = new Intl.NumberFormat('en-US');
// [key, name, value, description, percent, legend value] -- all computed by make_pies.py, sorted by value
const sets = {{
  ops: {{ unit: 'ops', rows: [
    {orows}
  ]}},
  size: {{ unit: 'words', rows: [
    {srows}
  ]}}
}};
function draw(id, lgId, s) {{
  const rows = s.rows;
  const colors = rows.map(r => COL[r[0]]);
  document.getElementById(lgId).innerHTML = rows.map((r, i) =>
    `<li><i style="background:${{colors[i]}}"></i><span>${{r[1]}}</span><span class="v">${{r[5]}}</span><span class="p">${{r[4]}}</span></li>`).join('');
  new Chart(document.getElementById(id), {{
    type: 'doughnut',
    data: {{ labels: rows.map(r => r[1]), datasets: [{{ data: rows.map(r => r[2]), backgroundColor: colors, borderColor: gap, borderWidth: 2, hoverOffset: 4 }}] }},
    options: {{ responsive: true, maintainAspectRatio: false, cutout: '58%',
      plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{
        label: c => ` ${{nf.format(c.raw)}} ${{s.unit}} (${{rows[c.dataIndex][4]}})`,
        afterLabel: c => ` ${{rows[c.dataIndex][3]}}`
      }} }} }} }}
  }});
}}
draw('opsPie', 'opsLg', sets.ops);
draw('sizePie', 'sizeLg', sets.size);
</script>""".format(otm="%.1f" % (OTOT / 1e6), on=len(orow), ow=pct(orow[0][2], OTOT), stm="%.1f" % (STOT / 1e6), sn=len(srow),
                    sl=pct(srow[0][2], STOT), oaria=aria(orow, OTOT), saria=aria(srow, STOT), ofb=fallback(orow), sfb=fallback(srow),
                    orows=js_rows(orow, OTOT), srows=js_rows(srow, STOT))
open(sys.argv[2], "w", encoding="utf-8", newline="\n").write(html)
print("ops total %d, size total %d" % (OTOT, STOT))
for k, n, v, dsc in orow:
    print("  ops  %-30s %11d %5s%%  %-7s %s" % (n, v, pct(v, OTOT), short(v), dsc))
for k, n, v, dsc in srow:
    print("  size %-30s %11d %5s%%  %-7s %s" % (n, v, pct(v, STOT), short(v), dsc))

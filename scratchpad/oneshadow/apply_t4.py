"""T4: the L-inf far reject in project_thing, BEFORE the two rotation multiplies.

Bound derived at runtime from sp_tzmax (no new baked fields, no sim/schema fan-out):
4.25 > sqrt(17), so bound = (tz_map<<2) + (tz_map>>2) + 2 over-approximates sqrt(17)*tzmax.
All arithmetic at FIVE nibbles so the <<2 cannot wrap; every rounding error ADMITS, never
rejects, so the picture provably cannot move."""
import pathlib
NL = chr(10)

p = pathlib.Path("src/fj/projection.fj")
s = p.read_text(encoding="utf-8")

anchor = "        hex.mov 8, pth_tr_y, sp_y" + NL + "        hex.sub 8, pth_tr_y, viewy" + NL
assert s.count(anchor) == 1
block = anchor + NL.join([
"        // T4 L-INF FAR REJECT (2026-09-03), before the two rotation multiplies. Measured in the",
"        // attribution round: this leaf runs 140-163 times a frame, accepts exactly 7, and 62-90%",
"        // of calls die on the depth test at the tz compare -- AFTER paying the two fixed_mul_lo",
"        // (~8.2k ops). Any ACCEPTED thing has tz <= sp_tzmax and |tx| <= tz<<2, so",
"        // d = sqrt(tz^2 + tx^2) <= sqrt(17)*sp_tzmax, and max(|tr_x|,|tr_y|) <= d. Rejecting on",
"        // |tr| > bound therefore kills only things the later chain rejects anyway.",
"        //",
"        // The bound comes from sp_tzmax AT RUNTIME -- no new baked field, no sim/throw-row or",
"        // schema fan-out: 4.25 = 4 + 1/4 > sqrt(17), bound = (tz_map<<2) + (tz_map>>2) + 2,",
"        // where tz_map is sp_tzmax's integer part. FIVE nibbles so the <<2 cannot wrap, and the",
"        // +2 covers both floors (the >>2 truncation, and |floor(tr)| understating |tr| by <1 on",
"        // the positive side). Every rounding error ADMITS a thing; none can reject one the old",
"        // chain accepted. sp_tzmax >= sp_tzmax2, so the one bound is conservative for the degfl",
"        // path as well.",
"        hex.zero 5, pth_dbound",
"        hex.mov 4, pth_dbound, sp_tzmax + 4*dw",
"        hex.shl_bit 5, pth_dbound",
"        hex.shl_bit 5, pth_dbound",
"        hex.zero 5, pth_dtest",
"        hex.mov 4, pth_dtest, sp_tzmax + 4*dw",
"        hex.shr_bit 5, pth_dtest",
"        hex.shr_bit 5, pth_dtest",
"        hex.add 5, pth_dbound, pth_dtest",
"        hex.inc 5, pth_dbound",
"        hex.inc 5, pth_dbound",
"        hex.mov 5, pth_dtest, pth_tr_x + 4*dw",
"        hex.abs 5, pth_dtest",
"        hex.cmp 5, pth_dtest, pth_dbound, linf_x_ok, linf_x_ok, reject",
"      linf_x_ok:",
"        hex.mov 5, pth_dtest, pth_tr_y + 4*dw",
"        hex.abs 5, pth_dtest",
"        hex.cmp 5, pth_dtest, pth_dbound, linf_y_ok, linf_y_ok, reject",
"      linf_y_ok:",
""])
s = s.replace(anchor, block, 1)

old = "@ past_far, past_minz, xscale_done, in_fov, x2_ok, x1_ok, cols_ok, h_ok, h_fits, clamp_tall, set_far, far_done, trig_calc, trig_have, reject, done, end, deg_far_hard"
new = "@ past_far, past_minz, xscale_done, in_fov, x2_ok, x1_ok, cols_ok, h_ok, h_fits, clamp_tall, set_far, far_done, trig_calc, trig_have, linf_x_ok, linf_y_ok, reject, done, end, deg_far_hard"
assert s.count(old) == 1
s = s.replace(old, new)

old = "degfl, thfar, pth_ang, pth_c_centerxfix"
new = "degfl, thfar, pth_ang, pth_dbound, pth_dtest, pth_c_centerxfix"
assert s.count(old) == 1
s = s.replace(old, new)
p.write_text(s, encoding="utf-8")

q = pathlib.Path("src/doomfj/wall_renderer.py")
t = q.read_text(encoding="utf-8")
old = '        "pth_ang: hex.vec 8",' + NL
new = old + '        "pth_dbound: hex.vec 8",' + NL + '        "pth_dtest: hex.vec 8",' + NL
assert t.count(old) == 1
t = t.replace(old, new)
q.write_text(t, encoding="utf-8")
print("T4 applied: projection.fj + two scratch registers")

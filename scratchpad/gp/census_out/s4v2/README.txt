S5 on the FROZEN combat scenario set v2 (843f28a) -- the census and the fight line for the handoff's
budget table. No build, no binary, no tracked file changed; the committed S5 census (census.run,
census_lib, census_report's unit costs) is driven unchanged by three new scripts.

Commands, from the repo root (in this order):
  python scratchpad/gp/census_v2.py            > scratchpad/gp/census_out/s4v2/run_s4v2.log      (~6 min)
  python scratchpad/gp/census_v2_fireball.py   > scratchpad/gp/census_out/s4v2/fireballs.txt     (~3 min)
  python scratchpad/gp/census_v2_report.py     > scratchpad/gp/census_out/s4v2/report_s4v2.txt   (seconds)

Files here:
  s4v2_<run>.jsonl   one JSON line per (frame, picture): today, todayR4, game (today's rules), rec (the
                     decided D3: a + c + d + e, b for projectiles and barrels)
  run_s4v2.log       the census run and its three controls per run: DIGEST (the model's final digest =
                     the frozen one), POSES (every frame's pose = the frozen one), PICTURE (the rec
                     picture's drawn population = the frozen `pops`, frame by frame) -- 11/11 PASS
  fireballs.txt      why no fireball is ever drawn in the set, and the price of a drawn one (staged fights)
  report_s4v2.txt    the tables: frames, census (today's rules vs decided D3), fight line by category and
                     its distribution (today's column and v2), the binding lines (i)-(iv) on B0 v2 and on
                     the strafe proxy, fireballs, caveats

# The episode build (scripts/build_episode.py)

started 2026-11-03 21:50:29; source e506c7d433b6c29c; flipjump b1365b5cde780df9ec93f2918d18cc5d6be2df28; 29.2 GB free on disk at the start

plan at the start: ~0.5 h of steps to run, 0.0 h of it a guess (never measured here)

**EPISODE: PASS**

| map | status | sha256 | byte-identical | size % of 2^27 | binding | B0 binding | speed (playthrough) | ms/frame | wall |
|---|---|---|---|---|---|---|---|---|---|
| E1M1 | PASS | 3a2c9564adbfcb07 | True | 37.40 | 14792784 | 14249841 | 12266909 | 62.7 | 90 min |
| E1M2 | PASS | 96b738ecc2039b3c | True | 60.45 | 17283193 | 16806922 | 14710806 | 63.5 | 116 min |
| E1M3 | PASS | 1feb6db9fb21acc0 | True | 44.82 | 13427447 | 14476506 | 11746196 | 76.9 | 105 min |
| E1M4 | PASS | ed6075e2eeea0ca3 | True | 48.13 | 11291909 | 19342561 | 13898994 | 90.2 | 133 min |
| E1M5 | PASS | 1bd109d61d0780b5 | True | 33.94 | 10933961 | 15745927 | 11639313 | 61.2 | 103 min |
| E1M6 | PASS | a59dad606f8ab9b2 | True | 64.07 | 25479320 | 25737929 | 17749651 | 110.5 | 189 min |
| E1M7 | PASS | 49b38d76c4fc7052 | True | 77.56 | 19461121 | 21711026 | 13965960 | 94.6 | 161 min |
| E1M8 | PASS | b8aa2750e95f0a07 | True | 20.86 | 10715756 | 9313030 | 9256781 | 32.4 | 44 min |
| E1M9 | PASS | 1171afc3d845e1f4 | True | 41.30 | 7138830 | 12564575 | 13424871 | 36.3 | 98 min |

## E1M1
record: docs/ship-gate.md 1 + 1b (blocked65, ship #2, 2026-10-28)

| step | status | wall | estimate | metrics / why | log |
|---|---|---|---|---|---|
| emit_check | PASS (skipped: passed, inputs unchanged) | 360 s | 6.0 min (measured) |  | build/episode_final/logs/E1M1_emit_check.log |
| build | PASS (skipped: passed, inputs unchanged) | 742 s | 12.4 min (measured) | build_s=740, cleaned=removed build/episode_final/generated_doom_e1m1 (0.06 GB), disk_free_gb=31.9 | build/episode_final/logs/E1M1_build.log |
| sha256 | PASS (skipped: passed, inputs unchanged) | 0 s | 0.0 min (measured) | bytes=17606504, census_identical=False, identical=True, recorded_sha256=3a2c9564adbfcb07a1378b6c0045ca2291246c4100abcafad68bae4af3815d3b, sha256=3a2c9564adbfcb07a1378b6c0045ca2291246c4100abcafad68bae4af3815d3b; BYTE-IDENTICAL to the record |  |
| p2a | PASS (skipped: passed, inputs unchanged) | 124 s | 2.1 min (measured) |  | build/episode_final/logs/E1M1_p2a.log |
| m2_std | PASS (skipped: passed, inputs unchanged) | 248 s | 4.1 min (measured) |  | build/episode_final/logs/E1M1_m2_std.log |
| m3 | PASS (skipped: passed, inputs unchanged) | 19 s | 0.3 min (measured) |  | build/episode_final/logs/E1M1_m3.log |
| hurt | PASS (skipped: passed, inputs unchanged) | 171 s | 2.8 min (measured) |  | build/episode_final/logs/E1M1_hurt.log |
| fight | PASS (skipped: passed, inputs unchanged) | 1730 s | 28.8 min (measured) |  | build/episode_final/logs/E1M1_fight.log |
| die | PASS (skipped: passed, inputs unchanged) | 234 s | 3.9 min (measured) |  | build/episode_final/logs/E1M1_die.log |
| b0 | PASS (skipped: passed, inputs unchanged) | 505 s | 8.4 min (measured) | b0_binding=14249841, b0_runs=11 | build/episode_final/logs/E1M1_b0.log |
| gamespeed_trail | PASS (skipped: passed, inputs unchanged) | 365 s | 6.1 min (measured) |  | build/episode_final/logs/E1M1_gamespeed_trail.log |
| gamespeed | PASS (skipped: passed, inputs unchanged) | 402 s | 6.7 min (measured) | binding=14792784, size_pct=37.4, size_words=50198748 | build/episode_final/logs/E1M1_gamespeed.log |
| playthrough | PASS (skipped: passed, inputs unchanged) | 85 s | 1.4 min (measured) | speed_binding=12266909 | build/episode_final/logs/E1M1_playthrough.log |
| feature_tests | PASS (skipped: passed, inputs unchanged) | 67 s | 1.1 min (measured) | passed=150 | build/episode_final/logs/E1M1_feature_tests.log |
| msframe | PASS (skipped: passed, inputs unchanged) | 370 s | 6.2 min (measured) | base_ms=62.7, ms_frame=62.7, verdict=NOT SEPARATED, yardstick_g=3.64 | build/episode_final/logs/E1M1_msframe.log |

## E1M2
record: docs/ship-gate.md 13 (v3, 2026-11-02: v2 on its own heat list)

| step | status | wall | estimate | metrics / why | log |
|---|---|---|---|---|---|
| emit_check | PASS (skipped: passed, inputs unchanged) | 387 s | 6.5 min (measured) |  | build/episode_final/logs/E1M2_emit_check.log |
| build | PASS (skipped: passed, inputs unchanged) | 1026 s | 17.1 min (measured) | build_s=1023, cleaned=removed build/episode_final/generated_doom_e1m2 (0.11 GB), disk_free_gb=31.7 | build/episode_final/logs/E1M2_build.log |
| sha256 | PASS (skipped: passed, inputs unchanged) | 0 s | 0.0 min (measured) | bytes=27930438, identical=True, recorded_sha256=96b738ecc2039b3c80f4598b1643f9c38aac69b09ee3eea18b46726e1eebf3ec, sha256=96b738ecc2039b3c80f4598b1643f9c38aac69b09ee3eea18b46726e1eebf3ec; BYTE-IDENTICAL to the record |  |
| p2a | PASS (skipped: passed, inputs unchanged) | 313 s | 5.2 min (measured) |  | build/episode_final/logs/E1M2_p2a.log |
| m2_std | PASS (skipped: passed, inputs unchanged) | 198 s | 3.3 min (measured) |  | build/episode_final/logs/E1M2_m2_std.log |
| m3 | PASS (skipped: passed, inputs unchanged) | 29 s | 0.5 min (measured) |  | build/episode_final/logs/E1M2_m3.log |
| hurt | PASS (skipped: passed, inputs unchanged) | 254 s | 4.2 min (measured) |  | build/episode_final/logs/E1M2_hurt.log |
| fight | PASS (skipped: passed, inputs unchanged) | 1129 s | 18.8 min (measured) |  | build/episode_final/logs/E1M2_fight.log |
| die | PASS (skipped: passed, inputs unchanged) | 258 s | 4.3 min (measured) |  | build/episode_final/logs/E1M2_die.log |
| b0 | PASS (skipped: passed, inputs unchanged) | 695 s | 11.6 min (measured) | b0_binding=16806922, b0_runs=11 | build/episode_final/logs/E1M2_b0.log |
| gamespeed_trail | PASS (skipped: passed, inputs unchanged) | 456 s | 7.6 min (measured) |  | build/episode_final/logs/E1M2_gamespeed_trail.log |
| gamespeed | PASS (skipped: passed, inputs unchanged) | 541 s | 9.0 min (measured) | binding=17283193, size_pct=60.45, size_words=81131558; size cap waived: 60.45% of 2^27 at v3 (v2 60.58%, r4 62.19%) -- the owner: "Size is ok" (docs/ship-gate.md 5) | build/episode_final/logs/E1M2_gamespeed.log |
| playthrough | PASS (skipped: passed, inputs unchanged) | 691 s | 11.5 min (measured) | speed_binding=14710806 | build/episode_final/logs/E1M2_playthrough.log |
| feature_tests | PASS (skipped: passed, inputs unchanged) | 507 s | 8.4 min (measured) | passed=111 | build/episode_final/logs/E1M2_feature_tests.log |
| msframe | PASS (skipped: passed, inputs unchanged) | 496 s | 8.3 min (measured) | base_ms=63.6, ms_frame=63.5, verdict=NOT SEPARATED, yardstick_g=3.64 | build/episode_final/logs/E1M2_msframe.log |

## E1M3
record: docs/ship-gate.md 13 (v2, 2026-11-02)

| step | status | wall | estimate | metrics / why | log |
|---|---|---|---|---|---|
| emit_check | PASS (skipped: passed, inputs unchanged) | 377 s | 6.3 min (measured) |  | build/episode_final/logs/E1M3_emit_check.log |
| build | PASS (skipped: passed, inputs unchanged) | 853 s | 14.2 min (measured) | build_s=852, cleaned=removed build/episode_final/generated_doom_e1m3 (0.10 GB), disk_free_gb=31.4 | build/episode_final/logs/E1M3_build.log |
| sha256 | PASS (skipped: passed, inputs unchanged) | 0 s | 0.0 min (measured) | bytes=20793990, identical=True, recorded_sha256=1feb6db9fb21acc0d89a18879437d06f100740ed51ba34a895edf64514cb5199, sha256=1feb6db9fb21acc0d89a18879437d06f100740ed51ba34a895edf64514cb5199; BYTE-IDENTICAL to the record |  |
| p2a | PASS (skipped: passed, inputs unchanged) | 104 s | 1.7 min (measured) |  | build/episode_final/logs/E1M3_p2a.log |
| m2_std | PASS (skipped: passed, inputs unchanged) | 48 s | 0.8 min (measured) |  | build/episode_final/logs/E1M3_m2_std.log |
| m3 | PASS (skipped: passed, inputs unchanged) | 21 s | 0.4 min (measured) |  | build/episode_final/logs/E1M3_m3.log |
| hurt | PASS (skipped: passed, inputs unchanged) | 316 s | 5.3 min (measured) |  | build/episode_final/logs/E1M3_hurt.log |
| fight | PASS (skipped: passed, inputs unchanged) | 1313 s | 21.9 min (measured) |  | build/episode_final/logs/E1M3_fight.log |
| die | PASS (skipped: passed, inputs unchanged) | 216 s | 3.6 min (measured) |  | build/episode_final/logs/E1M3_die.log |
| b0 | PASS (skipped: passed, inputs unchanged) | 817 s | 13.6 min (measured) | b0_binding=14476506, b0_runs=11 | build/episode_final/logs/E1M3_b0.log |
| gamespeed_trail | PASS (skipped: passed, inputs unchanged) | 600 s | 10.0 min (measured) |  | build/episode_final/logs/E1M3_gamespeed_trail.log |
| gamespeed | PASS (skipped: passed, inputs unchanged) | 647 s | 10.8 min (measured) | binding=13427447, size_pct=44.82, size_words=60154850; size cap waived: the owner 2026-10-24: above 43% of 2^27 is OK | build/episode_final/logs/E1M3_gamespeed.log |
| playthrough | PASS (skipped: passed, inputs unchanged) | 553 s | 9.2 min (measured) | speed_binding=11746196 | build/episode_final/logs/E1M3_playthrough.log |
| msframe | PASS (skipped: passed, inputs unchanged) | 441 s | 7.4 min (measured) | base_ms=76.2, ms_frame=76.9, verdict=NOT SEPARATED, yardstick_g=3.6 | build/episode_final/logs/E1M3_msframe.log |

## E1M4
record: docs/ship-gate.md 13 (v2, 2026-11-02)

| step | status | wall | estimate | metrics / why | log |
|---|---|---|---|---|---|
| emit_check | PASS (skipped: passed, inputs unchanged) | 399 s | 6.6 min (measured) |  | build/episode_final/logs/E1M4_emit_check.log |
| build | PASS (skipped: passed, inputs unchanged) | 941 s | 15.7 min (measured) | build_s=939, cleaned=removed build/episode_final/generated_doom_e1m4 (0.08 GB), disk_free_gb=31.1 | build/episode_final/logs/E1M4_build.log |
| sha256 | PASS (skipped: passed, inputs unchanged) | 0 s | 0.0 min (measured) | bytes=22618357, identical=True, recorded_sha256=ed6075e2eeea0ca34812f69ce56fc691513a5f9f0a9c166a8dabbc346bd1751b, sha256=ed6075e2eeea0ca34812f69ce56fc691513a5f9f0a9c166a8dabbc346bd1751b; BYTE-IDENTICAL to the record |  |
| p2a | PASS (skipped: passed, inputs unchanged) | 73 s | 1.2 min (measured) |  | build/episode_final/logs/E1M4_p2a.log |
| m2_std | PASS (skipped: passed, inputs unchanged) | 56 s | 0.9 min (measured) |  | build/episode_final/logs/E1M4_m2_std.log |
| m3 | PASS (skipped: passed, inputs unchanged) | 25 s | 0.4 min (measured) |  | build/episode_final/logs/E1M4_m3.log |
| hurt | PASS (skipped: passed, inputs unchanged) | 722 s | 12.0 min (measured) |  | build/episode_final/logs/E1M4_hurt.log |
| fight | PASS (skipped: passed, inputs unchanged) | 1982 s | 33.0 min (measured) |  | build/episode_final/logs/E1M4_fight.log |
| die | PASS (skipped: passed, inputs unchanged) | 244 s | 4.1 min (measured) |  | build/episode_final/logs/E1M4_die.log |
| b0 | PASS (skipped: passed, inputs unchanged) | 758 s | 12.6 min (measured) | b0_binding=19342561, b0_runs=11 | build/episode_final/logs/E1M4_b0.log |
| gamespeed_trail | PASS (skipped: passed, inputs unchanged) | 622 s | 10.4 min (measured) |  | build/episode_final/logs/E1M4_gamespeed_trail.log |
| gamespeed | PASS (skipped: passed, inputs unchanged) | 697 s | 11.6 min (measured) | binding=11291909, size_pct=48.13, size_words=64593636; size cap waived: the owner 2026-10-24: above 43% of 2^27 is OK | build/episode_final/logs/E1M4_gamespeed.log |
| playthrough | PASS (skipped: passed, inputs unchanged) | 964 s | 16.1 min (measured) | speed_binding=13898994 | build/episode_final/logs/E1M4_playthrough.log |
| msframe | PASS (skipped: passed, inputs unchanged) | 488 s | 8.1 min (measured) | base_ms=89.5, ms_frame=90.2, verdict=NOT SEPARATED, yardstick_g=3.59 | build/episode_final/logs/E1M4_msframe.log |

## E1M5
record: docs/ship-gate.md 13 (v2, 2026-11-02)

| step | status | wall | estimate | metrics / why | log |
|---|---|---|---|---|---|
| emit_check | PASS (skipped: passed, inputs unchanged) | 396 s | 6.6 min (measured) |  | build/episode_final/logs/E1M5_emit_check.log |
| build | PASS (skipped: passed, inputs unchanged) | 766 s | 12.8 min (measured) | build_s=764, cleaned=removed build/episode_final/generated_doom_e1m5 (0.05 GB), disk_free_gb=30.1 | build/episode_final/logs/E1M5_build.log |
| sha256 | PASS (skipped: passed, inputs unchanged) | 0 s | 0.0 min (measured) | bytes=16473595, identical=True, recorded_sha256=1bd109d61d0780b57647fb4bd76cf271733080778ea208e187c2f5db92d31b32, sha256=1bd109d61d0780b57647fb4bd76cf271733080778ea208e187c2f5db92d31b32; BYTE-IDENTICAL to the record |  |
| p2a | PASS (skipped: passed, inputs unchanged) | 65 s | 1.1 min (measured) |  | build/episode_final/logs/E1M5_p2a.log |
| m2_std | PASS (skipped: passed, inputs unchanged) | 950 s | 15.8 min (measured) |  | build/episode_final/logs/E1M5_m2_std.log |
| m3 | PASS (skipped: passed, inputs unchanged) | 20 s | 0.3 min (measured) |  | build/episode_final/logs/E1M5_m3.log |
| hurt | PASS (skipped: passed, inputs unchanged) | 325 s | 5.4 min (measured) |  | build/episode_final/logs/E1M5_hurt.log |
| fight | PASS (skipped: passed, inputs unchanged) | 704 s | 11.7 min (measured) |  | build/episode_final/logs/E1M5_fight.log |
| die | PASS (skipped: passed, inputs unchanged) | 157 s | 2.6 min (measured) |  | build/episode_final/logs/E1M5_die.log |
| b0 | PASS (skipped: passed, inputs unchanged) | 591 s | 9.8 min (measured) | b0_binding=15745927, b0_runs=11 | build/episode_final/logs/E1M5_b0.log |
| gamespeed_trail | PASS (skipped: passed, inputs unchanged) | 524 s | 8.7 min (measured) |  | build/episode_final/logs/E1M5_gamespeed_trail.log |
| gamespeed | PASS (skipped: passed, inputs unchanged) | 510 s | 8.5 min (measured) | binding=10933961, size_pct=33.94, size_words=45553672; size cap waived: the owner 2026-10-24: above 43% of 2^27 is OK | build/episode_final/logs/E1M5_gamespeed.log |
| playthrough | PASS (skipped: passed, inputs unchanged) | 803 s | 13.4 min (measured) | speed_binding=11639313 | build/episode_final/logs/E1M5_playthrough.log |
| msframe | PASS (skipped: passed, inputs unchanged) | 348 s | 5.8 min (measured) | base_ms=61.0, ms_frame=61.2, verdict=NOT SEPARATED, yardstick_g=3.59 | build/episode_final/logs/E1M5_msframe.log |

## E1M6
record: docs/ship-gate.md 12 (v3, 2026-11-01)

| step | status | wall | estimate | metrics / why | log |
|---|---|---|---|---|---|
| emit_check | PASS (skipped: passed, inputs unchanged) | 423 s | 7.1 min (measured) |  | build/episode_final/logs/E1M6_emit_check.log |
| build | PASS (skipped: passed, inputs unchanged) | 1159 s | 19.3 min (measured) | build_s=1155, cleaned=removed build/episode_final/generated_doom_e1m6 (0.11 GB), disk_free_gb=29.9 | build/episode_final/logs/E1M6_build.log |
| sha256 | PASS (skipped: passed, inputs unchanged) | 0 s | 0.0 min (measured) | bytes=29701428, identical=True, recorded_sha256=a59dad606f8ab9b29d2a6b3111d2de207febec50323fafa3aa8795d7e19b015b, sha256=a59dad606f8ab9b29d2a6b3111d2de207febec50323fafa3aa8795d7e19b015b; BYTE-IDENTICAL to the record |  |
| p2a | PASS (skipped: passed, inputs unchanged) | 342 s | 5.7 min (measured) |  | build/episode_final/logs/E1M6_p2a.log |
| m2_std | PASS (skipped: passed, inputs unchanged) | 3490 s | 58.2 min (measured) |  | build/episode_final/logs/E1M6_m2_std.log |
| m3 | PASS (skipped: passed, inputs unchanged) | 33 s | 0.5 min (measured) |  | build/episode_final/logs/E1M6_m3.log |
| hurt | PASS (skipped: passed, inputs unchanged) | 301 s | 5.0 min (measured) |  | build/episode_final/logs/E1M6_hurt.log |
| fight | PASS (skipped: passed, inputs unchanged) | 1828 s | 30.5 min (measured) |  | build/episode_final/logs/E1M6_fight.log |
| die | PASS (skipped: passed, inputs unchanged) | 259 s | 4.3 min (measured) |  | build/episode_final/logs/E1M6_die.log |
| b0 | PASS | 804 s | 14.5 min (measured) | b0_binding=25737929, b0_runs=11; over CAP-22, <= 25737929 recorded OVER at v3 (docs/ship-gate.md 12); the owner 2026-10-29: the playthrough's speed set binds | build/episode_final/logs/E1M6_b0.log |
| gamespeed_trail | PASS (skipped: passed, inputs unchanged) | 775 s | 12.9 min (measured) |  | build/episode_final/logs/E1M6_gamespeed_trail.log |
| gamespeed | PASS | 936 s | 16.9 min (measured) | binding=25479320, size_pct=64.07, size_words=85990364; over CAP-22, <= 25479320 recorded OVER at v3 (docs/ship-gate.md 12); the owner 2026-10-29: the playthrough's speed set binds; size cap waived: the owner 2026-10-24: above 43% of 2^27 is OK | build/episode_final/logs/E1M6_gamespeed.log |
| playthrough | PASS (skipped: passed, inputs unchanged) | 325 s | 5.4 min (measured) | speed_binding=17749651 | build/episode_final/logs/E1M6_playthrough.log |
| msframe | PASS (skipped: passed, inputs unchanged) | 654 s | 10.9 min (measured) | base_ms=109.6, ms_frame=110.5, verdict=NOT SEPARATED, yardstick_g=3.6 | build/episode_final/logs/E1M6_msframe.log |

## E1M7
record: docs/ship-gate.md 13 (v2, 2026-11-02)

| step | status | wall | estimate | metrics / why | log |
|---|---|---|---|---|---|
| emit_check | PASS (skipped: passed, inputs unchanged) | 441 s | 7.3 min (measured) |  | build/episode_final/logs/E1M7_emit_check.log |
| build | PASS (skipped: passed, inputs unchanged) | 1600 s | 26.7 min (measured) | build_s=1593, cleaned=removed build/episode_final/generated_doom_e1m7 (0.18 GB), disk_free_gb=29.8 | build/episode_final/logs/E1M7_build.log |
| sha256 | PASS (skipped: passed, inputs unchanged) | 0 s | 0.0 min (measured) | bytes=35544345, identical=True, recorded_sha256=49b38d76c4fc7052ae01627c265788b1c5c609f5e6305d265223c17a9735b8fd, sha256=49b38d76c4fc7052ae01627c265788b1c5c609f5e6305d265223c17a9735b8fd; BYTE-IDENTICAL to the record |  |
| p2a | PASS (skipped: passed, inputs unchanged) | 214 s | 3.6 min (measured) |  | build/episode_final/logs/E1M7_p2a.log |
| m2_std | PASS (skipped: passed, inputs unchanged) | 130 s | 2.2 min (measured) |  | build/episode_final/logs/E1M7_m2_std.log |
| m3 | PASS (skipped: passed, inputs unchanged) | 39 s | 0.7 min (measured) |  | build/episode_final/logs/E1M7_m3.log |
| hurt | PASS (skipped: passed, inputs unchanged) | 399 s | 6.6 min (measured) |  | build/episode_final/logs/E1M7_hurt.log |
| fight | PASS (skipped: passed, inputs unchanged) | 1762 s | 29.4 min (measured) |  | build/episode_final/logs/E1M7_fight.log |
| die | PASS (skipped: passed, inputs unchanged) | 484 s | 8.1 min (measured) |  | build/episode_final/logs/E1M7_die.log |
| b0 | PASS (skipped: passed, inputs unchanged) | 1026 s | 17.1 min (measured) | b0_binding=21711026, b0_runs=11 | build/episode_final/logs/E1M7_b0.log |
| gamespeed_trail | PASS (skipped: passed, inputs unchanged) | 874 s | 14.6 min (measured) |  | build/episode_final/logs/E1M7_gamespeed_trail.log |
| gamespeed | PASS (skipped: passed, inputs unchanged) | 1350 s | 22.5 min (measured) | binding=19461121, size_pct=77.56, size_words=104098214; size cap waived: the owner 2026-10-24: above 43% of 2^27 is OK | build/episode_final/logs/E1M7_gamespeed.log |
| playthrough | PASS (skipped: passed, inputs unchanged) | 439 s | 7.3 min (measured) | speed_binding=13965960 | build/episode_final/logs/E1M7_playthrough.log |
| msframe | PASS (skipped: passed, inputs unchanged) | 890 s | 14.8 min (measured) | base_ms=101.4, ms_frame=94.6, verdict=NOT SEPARATED, yardstick_g=3.61 | build/episode_final/logs/E1M7_msframe.log |

## E1M8
record: docs/ship-gate.md 13 (v2, 2026-11-02)

| step | status | wall | estimate | metrics / why | log |
|---|---|---|---|---|---|
| emit_check | PASS (skipped: passed, inputs unchanged) | 328 s | 5.5 min (measured) |  | build/episode_final/logs/E1M8_emit_check.log |
| build | PASS (skipped: passed, inputs unchanged) | 542 s | 9.0 min (measured) | build_s=541, cleaned=removed build/episode_final/generated_doom_e1m8 (0.05 GB), disk_free_gb=32.6 | build/episode_final/logs/E1M8_build.log |
| sha256 | PASS (skipped: passed, inputs unchanged) | 0 s | 0.0 min (measured) | bytes=9552582, identical=True, recorded_sha256=b8aa2750e95f0a07d8439cd08ebd1cd5d685a6beb4ea7710a1811b71cea1944e, sha256=b8aa2750e95f0a07d8439cd08ebd1cd5d685a6beb4ea7710a1811b71cea1944e; BYTE-IDENTICAL to the record |  |
| p2a | PASS (skipped: passed, inputs unchanged) | 6 s | 0.1 min (measured) |  | build/episode_final/logs/E1M8_p2a.log |
| m2_std | PASS (skipped: passed, inputs unchanged) | 212 s | 3.5 min (measured) |  | build/episode_final/logs/E1M8_m2_std.log |
| m3 | PASS (skipped: passed, inputs unchanged) | 11 s | 0.2 min (measured) |  | build/episode_final/logs/E1M8_m3.log |
| hurt | PASS (skipped: passed, inputs unchanged) | 6 s | 0.1 min (measured) |  | build/episode_final/logs/E1M8_hurt.log |
| fight | PASS (skipped: passed, inputs unchanged) | 25 s | 0.4 min (measured) |  | build/episode_final/logs/E1M8_fight.log |
| die | PASS (skipped: passed, inputs unchanged) | 67 s | 1.1 min (measured) |  | build/episode_final/logs/E1M8_die.log |
| b0 | PASS (skipped: passed, inputs unchanged) | 342 s | 5.7 min (measured) | b0_binding=9313030, b0_runs=11 | build/episode_final/logs/E1M8_b0.log |
| gamespeed_trail | PASS (skipped: passed, inputs unchanged) | 324 s | 5.4 min (measured) |  | build/episode_final/logs/E1M8_gamespeed_trail.log |
| gamespeed | PASS (skipped: passed, inputs unchanged) | 324 s | 5.4 min (measured) | binding=10715756, size_pct=20.86, size_words=27993760; size cap waived: the owner 2026-10-24: above 43% of 2^27 is OK | build/episode_final/logs/E1M8_gamespeed.log |
| playthrough | PASS (skipped: passed, inputs unchanged) | 255 s | 4.2 min (measured) | speed_binding=9256781 | build/episode_final/logs/E1M8_playthrough.log |
| msframe | PASS (skipped: passed, inputs unchanged) | 194 s | 3.2 min (measured) | base_ms=32.2, ms_frame=32.4, verdict=NOT SEPARATED, yardstick_g=3.65 | build/episode_final/logs/E1M8_msframe.log |

## E1M9
record: docs/ship-gate.md 13 (v2, 2026-11-02)

| step | status | wall | estimate | metrics / why | log |
|---|---|---|---|---|---|
| emit_check | PASS (skipped: passed, inputs unchanged) | 388 s | 6.5 min (measured) |  | build/episode_final/logs/E1M9_emit_check.log |
| build | PASS (skipped: passed, inputs unchanged) | 828 s | 13.8 min (measured) | build_s=826, cleaned=removed build/episode_final/generated_doom_e1m9 (0.09 GB), disk_free_gb=32.5 | build/episode_final/logs/E1M9_build.log |
| sha256 | PASS (skipped: passed, inputs unchanged) | 0 s | 0.0 min (measured) | bytes=18786219, identical=True, recorded_sha256=1171afc3d845e1f426d624f4db26a01e472adbb1f60e5c9766778740c0eca01d, sha256=1171afc3d845e1f426d624f4db26a01e472adbb1f60e5c9766778740c0eca01d; BYTE-IDENTICAL to the record |  |
| p2a | PASS (skipped: passed, inputs unchanged) | 99 s | 1.6 min (measured) |  | build/episode_final/logs/E1M9_p2a.log |
| m2_std | PASS (skipped: passed, inputs unchanged) | 97 s | 1.6 min (measured) |  | build/episode_final/logs/E1M9_m2_std.log |
| m3 | PASS (skipped: passed, inputs unchanged) | 14 s | 0.2 min (measured) |  | build/episode_final/logs/E1M9_m3.log |
| hurt | PASS (skipped: passed, inputs unchanged) | 222 s | 3.7 min (measured) |  | build/episode_final/logs/E1M9_hurt.log |
| fight | PASS (skipped: passed, inputs unchanged) | 1364 s | 22.7 min (measured) |  | build/episode_final/logs/E1M9_fight.log |
| die | PASS (skipped: passed, inputs unchanged) | 209 s | 3.5 min (measured) |  | build/episode_final/logs/E1M9_die.log |
| b0 | PASS (skipped: passed, inputs unchanged) | 600 s | 10.0 min (measured) | b0_binding=12564575, b0_runs=11 | build/episode_final/logs/E1M9_b0.log |
| gamespeed_trail | PASS (skipped: passed, inputs unchanged) | 387 s | 6.5 min (measured) |  | build/episode_final/logs/E1M9_gamespeed_trail.log |
| gamespeed | PASS (skipped: passed, inputs unchanged) | 431 s | 7.2 min (measured) | binding=7138830, size_pct=41.3, size_words=55428628; size cap waived: the owner 2026-10-24: above 43% of 2^27 is OK | build/episode_final/logs/E1M9_gamespeed.log |
| playthrough | PASS (skipped: passed, inputs unchanged) | 904 s | 15.1 min (measured) | speed_binding=13424871 | build/episode_final/logs/E1M9_playthrough.log |
| msframe | PASS (skipped: passed, inputs unchanged) | 325 s | 5.4 min (measured) | base_ms=36.3, ms_frame=36.3, verdict=NOT SEPARATED, yardstick_g=3.64 | build/episode_final/logs/E1M9_msframe.log |

# The episode build (scripts/build_episode.py)

started 2026-11-15 09:58:51; source 8e82dd02ad6ca4a6; flipjump 7a49ef12865e94f265199b00d75285b68242b0cb; 21.0 GB free on disk at the start

plan at the start: ~3.9 h of steps to run, 2.0 h of it a guess (never measured here)

**EPISODE: PASS**

| map | status | sha256 | byte-identical | size % of 2^27 | binding | B0 binding | speed (playthrough) | ms/frame | wall |
|---|---|---|---|---|---|---|---|---|---|
| E1M2 | PASS | 96b738ecc2039b3c | True | - | - | - | - | - | 18 min |
| E1M3 | PASS | 1feb6db9fb21acc0 | True | - | - | - | - | - | 15 min |
| E1M4 | PASS | ed6075e2eeea0ca3 | True | - | - | - | - | - | 15 min |
| E1M5 | PASS | 1bd109d61d0780b5 | True | - | - | - | - | - | 12 min |
| E1M6 | PASS | a59dad606f8ab9b2 | True | - | - | - | - | - | 19 min |
| E1M7 | PASS | 49b38d76c4fc7052 | True | - | - | - | - | - | 25 min |
| E1M8 | PASS | b8aa2750e95f0a07 | True | - | - | - | - | - | 9 min |
| E1M9 | PASS | 1171afc3d845e1f4 | True | - | - | - | - | - | 14 min |

## E1M2
record: docs/ship-gate.md 13 (v3, 2026-11-02: v2 on its own heat list)

| step | status | wall | estimate | metrics / why | log |
|---|---|---|---|---|---|
| build | PASS | 1067 s | 120.0 min (guess) | build_s=1066, cleaned=removed build/episode_7a49/generated_doom_e1m2 (0.11 GB), disk_free_gb=21.0 | build/episode_7a49/logs/E1M2_build.log |
| sha256 | PASS | 0 s | 0.0 min (guess) | bytes=27930438, identical=True, recorded_sha256=96b738ecc2039b3c80f4598b1643f9c38aac69b09ee3eea18b46726e1eebf3ec, sha256=96b738ecc2039b3c80f4598b1643f9c38aac69b09ee3eea18b46726e1eebf3ec; BYTE-IDENTICAL to the record |  |

## E1M3
record: docs/ship-gate.md 13 (v2, 2026-11-02)

| step | status | wall | estimate | metrics / why | log |
|---|---|---|---|---|---|
| build | PASS | 879 s | 17.8 min (measured on E1M2) | build_s=878, cleaned=removed build/episode_7a49/generated_doom_e1m3 (0.10 GB), disk_free_gb=20.8 | build/episode_7a49/logs/E1M3_build.log |
| sha256 | PASS | 0 s | 0.0 min (measured on E1M2) | bytes=20793990, identical=True, recorded_sha256=1feb6db9fb21acc0d89a18879437d06f100740ed51ba34a895edf64514cb5199, sha256=1feb6db9fb21acc0d89a18879437d06f100740ed51ba34a895edf64514cb5199; BYTE-IDENTICAL to the record |  |

## E1M4
record: docs/ship-gate.md 13 (v2, 2026-11-02)

| step | status | wall | estimate | metrics / why | log |
|---|---|---|---|---|---|
| build | PASS | 906 s | 16.2 min (measured on E1M2/E1M3) | build_s=905, cleaned=removed build/episode_7a49/generated_doom_e1m4 (0.08 GB), disk_free_gb=20.8 | build/episode_7a49/logs/E1M4_build.log |
| sha256 | PASS | 0 s | 0.0 min (measured on E1M2/E1M3) | bytes=22618357, identical=True, recorded_sha256=ed6075e2eeea0ca34812f69ce56fc691513a5f9f0a9c166a8dabbc346bd1751b, sha256=ed6075e2eeea0ca34812f69ce56fc691513a5f9f0a9c166a8dabbc346bd1751b; BYTE-IDENTICAL to the record |  |

## E1M5
record: docs/ship-gate.md 13 (v2, 2026-11-02)

| step | status | wall | estimate | metrics / why | log |
|---|---|---|---|---|---|
| build | PASS | 737 s | 15.8 min (measured on E1M2/E1M3/E1M4) | build_s=736, cleaned=removed build/episode_7a49/generated_doom_e1m5 (0.05 GB), disk_free_gb=20.5 | build/episode_7a49/logs/E1M5_build.log |
| sha256 | PASS | 0 s | 0.0 min (measured on E1M2/E1M3/E1M4) | bytes=16473595, identical=True, recorded_sha256=1bd109d61d0780b57647fb4bd76cf271733080778ea208e187c2f5db92d31b32, sha256=1bd109d61d0780b57647fb4bd76cf271733080778ea208e187c2f5db92d31b32; BYTE-IDENTICAL to the record |  |

## E1M6
record: docs/ship-gate.md 12 (v3, 2026-11-01)

| step | status | wall | estimate | metrics / why | log |
|---|---|---|---|---|---|
| build | PASS | 1124 s | 15.0 min (measured on E1M2/E1M3/E1M4/E1M5) | build_s=1123, cleaned=removed build/episode_7a49/generated_doom_e1m6 (0.11 GB), disk_free_gb=20.5 | build/episode_7a49/logs/E1M6_build.log |
| sha256 | PASS | 0 s | 0.0 min (measured on E1M2/E1M3/E1M4/E1M5) | bytes=29701428, identical=True, recorded_sha256=a59dad606f8ab9b29d2a6b3111d2de207febec50323fafa3aa8795d7e19b015b, sha256=a59dad606f8ab9b29d2a6b3111d2de207febec50323fafa3aa8795d7e19b015b; BYTE-IDENTICAL to the record |  |

## E1M7
record: docs/ship-gate.md 13 (v2, 2026-11-02)

| step | status | wall | estimate | metrics / why | log |
|---|---|---|---|---|---|
| build | PASS | 1515 s | 15.7 min (measured on E1M2/E1M3/E1M4/E1M5/E1M6) | build_s=1514, cleaned=removed build/episode_7a49/generated_doom_e1m7 (0.18 GB), disk_free_gb=20.4 | build/episode_7a49/logs/E1M7_build.log |
| sha256 | PASS | 0 s | 0.0 min (measured on E1M2/E1M3/E1M4/E1M5/E1M6) | bytes=35544345, identical=True, recorded_sha256=49b38d76c4fc7052ae01627c265788b1c5c609f5e6305d265223c17a9735b8fd, sha256=49b38d76c4fc7052ae01627c265788b1c5c609f5e6305d265223c17a9735b8fd; BYTE-IDENTICAL to the record |  |

## E1M8
record: docs/ship-gate.md 13 (v2, 2026-11-02)

| step | status | wall | estimate | metrics / why | log |
|---|---|---|---|---|---|
| build | PASS | 557 s | 17.3 min (measured on E1M2/E1M3/E1M4/E1M5/E1M6/E1M7) | build_s=556, cleaned=removed build/episode_7a49/generated_doom_e1m8 (0.05 GB), disk_free_gb=20.3 | build/episode_7a49/logs/E1M8_build.log |
| sha256 | PASS | 0 s | 0.0 min (measured on E1M2/E1M3/E1M4/E1M5/E1M6/E1M7) | bytes=9552582, identical=True, recorded_sha256=b8aa2750e95f0a07d8439cd08ebd1cd5d685a6beb4ea7710a1811b71cea1944e, sha256=b8aa2750e95f0a07d8439cd08ebd1cd5d685a6beb4ea7710a1811b71cea1944e; BYTE-IDENTICAL to the record |  |

## E1M9
record: docs/ship-gate.md 13 (v2, 2026-11-02)

| step | status | wall | estimate | metrics / why | log |
|---|---|---|---|---|---|
| build | PASS | 857 s | 16.2 min (measured on E1M2/E1M3/E1M4/E1M5/E1M6/E1M7/E1M8) | build_s=856, cleaned=removed build/episode_7a49/generated_doom_e1m9 (0.09 GB), disk_free_gb=20.3 | build/episode_7a49/logs/E1M9_build.log |
| sha256 | PASS | 0 s | 0.0 min (measured on E1M2/E1M3/E1M4/E1M5/E1M6/E1M7/E1M8) | bytes=18786219, identical=True, recorded_sha256=1171afc3d845e1f426d624f4db26a01e472adbb1f60e5c9766778740c0eca01d, sha256=1171afc3d845e1f426d624f4db26a01e472adbb1f60e5c9766778740c0eca01d; BYTE-IDENTICAL to the record |  |

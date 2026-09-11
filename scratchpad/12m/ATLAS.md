# ATLAS -- where the ops go (measured)

Built by `scratchpad/12m/atlas.py` from 8 per-op profiles of `P2-6.fjm`.
Method: every executed op is attributed to the nearest label at or below its address; that
label's name IS its macro call stack, so INCLUSIVE = ops anywhere inside a macro (the pool
size) and EXCLUSIVE = ops in that macro's own body (where a fix must land).

| profile | viewpoint | ops | coverage |
|---|---|---|---|
| P2-6.h0_0 | (589,-33,0xc0000000) | 3,341,192 | 100.000% |
| P2-6.h14_3 | (77,1503,0x40000000) | 11,245,155 | 100.000% |
| P2-6.h28_6 | (2893,1503,0x0) | 14,987,033 | 100.000% |
| P2-6.h42_9 | (2381,-289,0xc0000000) | 17,013,401 | 100.000% |
| P2-6.h57_1 | (2893,2015,0x80000000) | 19,307,813 | 100.000% |
| P2-6.h71_4 | (2637,991,0x0) | 22,021,372 | 100.000% |
| P2-6.h85_7 | (333,-33,0x40000000) | 25,302,041 | 100.000% |
| P2-6.h100_0 | (2637,991,0x40000000) | 37,916,768 | 100.000% |

The MEDIAN column below is the profile whose op count is the median of the profiled
set (`P2-6.h57_1`, 19,307,813 ops); MIN and MAX are the cheapest and dearest profiled frames. The
campaign ships on the 260-frame sweep median, so MEDIAN is the column that ranks.

## Pool table -- INCLUSIVE ops per macro (all call sites summed)

| macro | median frame | min frame | max frame | share of median |
|---|---:|---:|---:|---:|
| `hex.exact_xor` | 8,811,030 | 1,680,766 | 16,150,027 | 45.63% |
| `hex.xor` | 8,811,030 | 1,680,766 | 16,150,027 | 45.63% |
| `frame.seg_pass2_leaf_body_lines` | 7,371,955 | 2,508,077 | 18,444,056 | 38.18% |
| `frame.seg_pass1_leaf_body_ts` | 4,466,123 | 1,255 | 4,633,403 | 23.13% |
| `hex.mov` | 4,228,401 | 673,941 | 8,299,586 | 21.90% |
| `hex.zero` | 4,038,149 | 736,614 | 7,870,887 | 20.91% |
| `stream.emit_col_lines` | 3,813,883 | 509,331 | 13,119,250 | 19.75% |
| `frame.ts_step_faces` | 3,276,489 | 2 | 3,517,856 | 16.97% |
| `frame.thing_record_body` | 2,307,796 | 211,124 | 6,273,338 | 11.95% |
| `hex.fixed_mul_lo.row` | 1,960,903 | 65,086 | 2,271,148 | 10.16% |
| `hex.fixed_mul_lo` | 1,881,451 | 21,221 | 2,008,149 | 9.74% |
| `hex.add_mul` | 1,844,048 | 59,600 | 2,131,681 | 9.55% |
| `proj.wall_x_range_m` | 1,744,608 | 29,636 | 2,065,818 | 9.04% |
| `hex.xor_zero` | 1,706,321 | 289,893 | 2,831,549 | 8.84% |
| `hex.double_exact_xor` | 1,706,321 | 289,893 | 2,831,549 | 8.84% |
| `hex.double_xor` | 1,706,321 | 289,893 | 2,831,549 | 8.84% |
| `proj.project_thing` | 1,604,241 | 113,796 | 1,548,433 | 8.31% |
| `frame.dance_boundary` | 1,491,021 | 330,330 | 2,539,779 | 7.72% |
| `stream.steps_splice_f` | 1,432,716 | 43,372 | 1,966,009 | 7.42% |
| `frame.ts_piece_store` | 1,432,304 | 0 | 1,525,447 | 7.42% |
| `hex.triple_exact_xor` | 1,398,329 | 185,779 | 4,839,523 | 7.24% |
| `hex.address_and_variable_triple_xor` | 1,398,329 | 185,779 | 4,839,523 | 7.24% |
| `stream.steps_face` | 1,380,693 | 53,492 | 1,766,345 | 7.15% |
| `frame.seg_pass1_leaf_body_lines` | 1,136,063 | 37,215 | 1,666,771 | 5.88% |
| `hex.cmp` | 1,068,175 | 373,518 | 1,753,585 | 5.53% |
| `proj.wall_scale_setup_m` | 1,008,820 | 72,716 | 1,726,516 | 5.22% |
| `frame.arm5` | 989,207 | 139,878 | 1,748,684 | 5.12% |
| `frame.add8_chain` | 935,662 | 253,620 | 1,784,439 | 4.85% |
| `stream.steps_splice_c` | 913,089 | 27,862 | 816,970 | 4.73% |
| `frame.sub8_chain` | 881,260 | 187,470 | 921,691 | 4.56% |
| `stl.startup_and_init_all` | 837,748 | 81,783 | 1,206,406 | 4.34% |
| `hex.tables.init_all` | 828,238 | 80,821 | 1,168,858 | 4.29% |
| `hex.init` | 828,238 | 80,821 | 1,168,858 | 4.29% |
| `hex.add_constant` | 819,397 | 204,102 | 1,844,281 | 4.24% |
| `frame.lines_steps_load2` | 807,249 | 53,040 | 856,553 | 4.18% |
| `frame.write_byte5` | 792,518 | 0 | 1,420,342 | 4.10% |
| `hex.scmp` | 783,737 | 167,335 | 2,815,168 | 4.06% |
| `hex.cmp.cmp_eq_next` | 781,807 | 258,734 | 1,425,206 | 4.05% |
| `frame.write_byte_and_inc5` | 772,979 | 6 | 1,423,516 | 4.00% |
| `hex.add.add_constant_with_leading_zeros` | 756,711 | 188,867 | 1,700,391 | 3.92% |
| `hex.add.add_hex_shifted_constant` | 756,711 | 188,867 | 1,700,391 | 3.92% |
| `proj.point_to_angle` | 749,461 | 15,880 | 962,173 | 3.88% |
| `hex.add_shifted` | 748,850 | 186,932 | 1,682,279 | 3.88% |
| `frame.ts_piece_wr` | 746,085 | 0 | 814,675 | 3.86% |
| `proj.point_on_side_leaf` | 710,388 | 71,640 | 875,393 | 3.68% |

## Where it lands -- EXCLUSIVE ops per macro body

| macro body | median frame | share |
|---|---:|---:|
| `hex.exact_xor` | 8,811,030 | 45.63% |
| `hex.double_exact_xor` | 1,706,321 | 8.84% |
| `hex.triple_exact_xor` | 1,398,329 | 7.24% |
| ~~`<top level: distscale>`~~ ⚠ ARTIFACT | ~~785,798~~ | ~~4.07%~~ |

⚠ The `distscale` row above is an OVER-ATTRIBUTION ARTIFACT, not a real cost (FINDINGS BA).
`distscale` is the last top-level label, so every op after it in the address space was
credited to it; 0 of the attributed ops were inside the table. `hotpath.py` now guards
against this and refuses to credit an op sitting >4096 ops past a bare label.

| `stl.comp_if1` | 445,288 | 2.31% |
| `hex.mul.init` | 405,775 | 2.10% |
| `hex.tables.clean_table_entry__table` | 325,583 | 1.69% |
| `hex.add.clear_carry` | 301,228 | 1.56% |
| `hex.add_mul` | 272,517 | 1.41% |
| `frame.add8_chain` | 265,994 | 1.38% |
| `frame.sub8_chain` | 258,392 | 1.34% |
| `hex.if_flags` | 221,620 | 1.15% |
| `hex.pointers.xor_hex_to_flip_ptr` | 216,520 | 1.12% |
| `hex.shifts.shl_bit_once` | 192,100 | 0.99% |
| `hex.cmp` | 187,568 | 0.97% |
| `hex.mov` | 180,048 | 0.93% |
| `hex.tables.jump_to_table_entry` | 178,486 | 0.92% |
| `<top level: hex.tables.ret>` | 139,975 | 0.72% |
| `hex.shifts.shr_bit_once` | 134,184 | 0.69% |
| `frame.arm5` | 107,421 | 0.56% |
| `<top level: hex.tables.res>` | 98,385 | 0.51% |
| `<top level: hex.add.dst>` | 93,577 | 0.48% |
| `bit.exact_xor` | 87,973 | 0.46% |
| `hex.add.init` | 87,813 | 0.45% |
| `hex.fixed_mul_lo.row` | 83,385 | 0.43% |
| `<top level: hex.mul.dst>` | 81,405 | 0.42% |
| `hex.mul.clear_carry` | 71,518 | 0.37% |
| `frame.sub4_chain` | 67,794 | 0.35% |
| `hex.pointers.read_cell_from_inners_ptrs` | 66,212 | 0.34% |
| `hex.add_constant` | 62,686 | 0.32% |
| `<top level: hex.mul.add_carry_dst>` | 60,554 | 0.31% |
| `byte.emit` | 59,218 | 0.31% |
| `frame.sub10_chain` | 54,373 | 0.28% |
| `hex.fixed_mul_lo` | 51,937 | 0.27% |
| `hex.if1` | 45,332 | 0.23% |
| `frame.add4_chain` | 43,007 | 0.22% |
| `hex.if0` | 42,958 | 0.22% |
| `<top level: hex.sub.dst>` | 42,676 | 0.22% |
| `stl.comp_if0` | 37,268 | 0.19% |
| `<top level: hex.cmp.dst>` | 33,940 | 0.18% |
| `<top level: hex.pointers.read_byte>` | 33,671 | 0.17% |
| `hex.inc.step` | 30,893 | 0.16% |
| `hex.sub.init` | 30,826 | 0.16% |
| `<top level: hex.pointers.to_ptr_var>` | 30,515 | 0.16% |
| `hex.cmp.init` | 28,737 | 0.15% |

## THE ACTIONABLE TABLE -- per hand-written call site

The deepest call site that lies in a hand-written .fj source. Everything below it is
stl machinery that this line asked for, so this is the line that has to change.

| site | macro called | median frame | min | max | share of median |
|---|---|---:|---:|---:|---:|
| `f2:l104` | `hex.add_mul` | 1,844,048 | 59,600 | 2,131,681 | 9.55% |
| `f5:l1546` | `hex.xor` | 702,752 | 157,016 | 1,175,761 | 3.64% |
| `f5:l1545` | `hex.xor_zero` | 685,879 | 152,840 | 1,190,635 | 3.55% |
| `f8:l1090` | `w1rpat.walk` | 653,910 | 383,066 | 84,318 | 3.39% |
| `f8:l607` | `w1rpat.walk_win` | 543,429 | 50,200 | 841,561 | 2.81% |
| `f5:l1889` | `hex.address_and_variable_triple_xor` | 459,696 | 64,275 | 819,660 | 2.38% |
| `f5:l1890` | `hex.address_and_variable_triple_xor` | 422,090 | 60,243 | 745,952 | 2.19% |
| `f5:l1940` | `hex.pointers.xor_byte_to_flip_ptr` | 244,750 | 0 | 441,845 | 1.27% |
| `f5:l949` | `hex.scmp` | 178,684 | 0 | 210,907 | 0.93% |
| `f5:l1572` | `hex.mov` | 173,197 | 16,255 | 264,958 | 0.90% |
| `f5:l1953` | `hex.ptr_inc` | 154,600 | 641 | 301,856 | 0.80% |
| `f5:l1944` | `hex.ptr_inc` | 135,602 | 6 | 251,471 | 0.70% |
| `f5:l1032` | `hex.read_hex` | 135,096 | 0 | 169,042 | 0.70% |
| `f2:l86` | `hex.mov` | 135,090 | 1,769 | 155,221 | 0.70% |
| `f5:l953` | `hex.scmp` | 126,251 | 0 | 107,153 | 0.65% |
| `f2:l88` | `hex.mov` | 125,255 | 1,777 | 139,955 | 0.65% |
| `f5:l969` | `hex.scmp` | 122,906 | 0 | 108,271 | 0.64% |
| `f5:l898` | `hex.mov` | 121,972 | 0 | 119,116 | 0.63% |
| `f4:l1050` | `hex.div` | 120,753 | 8,552 | 201,396 | 0.63% |
| `f2:l90` | `hex.zero` | 119,847 | 1,512 | 138,647 | 0.62% |
| `f4:l1055` | `hex.div` | 116,367 | 28 | 190,777 | 0.60% |
| `f2:l92` | `hex.mov` | 112,881 | 2,969 | 129,324 | 0.58% |
| `f5:l1399` | `hex.read_byte` | 110,473 | 2,400 | 269,784 | 0.57% |
| `f8:l1006` | `hex.read_byte_and_inc` | 102,872 | 1,280 | 834,467 | 0.53% |
| `f5:l1547` | `hex.xor` | 102,390 | 20,474 | 173,383 | 0.53% |
| `f5:l1574` | `hex.shr_bit` | 90,635 | 7,622 | 134,561 | 0.47% |
| `f5:l458` | `hex.scmp` | 87,024 | 86,719 | 86,987 | 0.45% |
| `f8:l893` | `w1rpat.walk_win` | 86,243 | 0 | 381,317 | 0.45% |
| `f5:l2649` | `hex.write_hex_and_inc` | 83,576 | 81,698 | 84,012 | 0.43% |
| `f5:l1575` | `hex.shl_hex` | 79,287 | 11,282 | 113,754 | 0.41% |
| `f5:l1576` | `frame.add8_chain` | 77,686 | 13,956 | 120,436 | 0.40% |
| `f8:l1008` | `hex.read_byte_and_inc` | 75,455 | 0 | 734,109 | 0.39% |
| `f5:l1295` | `hex.add` | 71,598 | 0 | 81,434 | 0.37% |
| `f5:l1284` | `hex.add` | 65,015 | 0 | 58,118 | 0.34% |
| `f4:l1641` | `hex.scmp` | 63,744 | 67,558 | 63,462 | 0.33% |
| `f5:l1217` | `hex.read_byte` | 63,686 | 0 | 69,265 | 0.33% |
| `f5:l1938` | `hex.pointers.read_byte_from_inners_ptrs` | 63,013 | 0 | 115,366 | 0.33% |
| `f4:l1713` | `hex.mov` | 62,458 | 6,703 | 75,572 | 0.32% |
| `f8:l1016` | `hex.scmp` | 62,405 | 0 | 604,511 | 0.32% |
| `f4:l1616` | `hex.mov` | 59,927 | 61,125 | 60,025 | 0.31% |
| `f5:l1573` | `hex.shl_hex` | 58,499 | 7,123 | 88,600 | 0.30% |
| `f4:l1715` | `hex.mov` | 57,753 | 6,585 | 70,603 | 0.30% |
| `f5:l2031` | `hex.mov` | 57,273 | 0 | 58,549 | 0.30% |
| `f4:l1627` | `hex.mov` | 54,731 | 60,958 | 54,616 | 0.28% |
| `f5:l1937` | `frame.arm5` | 54,700 | 0 | 91,276 | 0.28% |

## Per call SITE -- the innermost (caller file:line -> macro) pairs

f<i> is the i-th file passed to the assembler: f1=fj_consts, f2=fixed_point, f3=present, f4=projection, f5=frame_render, f6=plane_render, f7=plane_bands, f8=stream_render, f9=e1m1_00_entry, f10=e1m1_01_tables, f11=e1m1_02_main, f12=e1m1_03_segconsts, f13=e1m1_04_walk, f14=e1m1_05_state, f15=e1m1_06_banks

| site | macro | median frame | share |
|---|---|---:|---:|
| `s16:l12` | `hex.exact_xor` | 8,811,030 | 45.63% |
| `s16:l77` | `hex.double_exact_xor` | 1,706,321 | 8.84% |
| `s16:l217` | `hex.triple_exact_xor` | 1,398,329 | 7.24% |
| `s15:l65` | `stl.comp_if1` | 445,288 | 2.31% |
| `s21:l32` | `hex.mul.init` | 405,775 | 2.10% |
| `s21:l61` | `hex.tables.clean_table_entry__table` | 275,087 | 1.42% |
| `s24:l26` | `hex.add_mul` | 272,517 | 1.41% |
| `s27:l107` | `hex.pointers.xor_hex_to_flip_ptr` | 207,560 | 1.08% |
| `s19:l10` | `hex.shifts.shl_bit_once` | 168,042 | 0.87% |
| `s17:l13` | `hex.tables.jump_to_table_entry` | 163,997 | 0.85% |
| `s20:l32` | `hex.if_flags` | 139,980 | 0.72% |
| `s20:l128` | `hex.cmp` | 122,453 | 0.63% |
| `s17:l33` | `hex.add.clear_carry` | 110,132 | 0.57% |
| `s19:l19` | `hex.shifts.shr_bit_once` | 104,756 | 0.54% |
| `s17:l31` | `hex.add.clear_carry` | 92,837 | 0.48% |
| `s5:l9` | `bit.exact_xor` | 87,973 | 0.46% |
| `s21:l34` | `hex.add.init` | 87,813 | 0.45% |
| `s24:l92` | `hex.add.clear_carry` | 80,555 | 0.42% |
| `f5:l1576` | `frame.add8_chain` | 77,686 | 0.40% |
| `s24:l24` | `hex.mul.clear_carry` | 68,376 | 0.35% |
| `s28:l45` | `hex.pointers.read_cell_from_inners_ptrs` | 66,212 | 0.34% |
| `s20:l122` | `hex.cmp` | 65,115 | 0.34% |
| `f5:l1937` | `frame.arm5` | 54,700 | 0.28% |
| `f2:l91` | `hex.fixed_mul_lo.row` | 46,974 | 0.24% |
| `f4:l239` | `frame.add8_chain` | 46,448 | 0.24% |
| `s20:l49` | `hex.if1` | 40,601 | 0.21% |
| `f5:l916` | `frame.sub8_chain` | 32,592 | 0.17% |
| `s21:l35` | `hex.sub.init` | 30,826 | 0.16% |
| `s19:l18` | `hex.shifts.shr_bit_once` | 29,428 | 0.15% |
| `s21:l33` | `hex.cmp.init` | 28,737 | 0.15% |
| `f5:l918` | `frame.sub8_chain` | 28,487 | 0.15% |
| `f5:l1950` | `frame.arm5` | 28,075 | 0.15% |
| `f4:l1714` | `frame.sub10_chain` | 27,367 | 0.14% |
| `f4:l1716` | `frame.sub10_chain` | 27,006 | 0.14% |
| `s32:l10` | `hex.add_constant` | 26,964 | 0.14% |
| `f5:l921` | `frame.sub8_chain` | 26,758 | 0.14% |
| `f10:l108457` | `byte.init` | 26,500 | 0.14% |
| `f5:l1958` | `frame.add8_chain` | 25,305 | 0.13% |
| `f10:l190398` | `cm.init` | 24,740 | 0.13% |
| `s19:l35` | `stl.comp_if0` | 24,315 | 0.13% |
| `s19:l9` | `hex.shifts.shl_bit_once` | 24,058 | 0.12% |
| `f4:l1628` | `frame.sub8_chain` | 23,840 | 0.12% |
| `s17:l62` | `hex.add_shifted` | 23,766 | 0.12% |
| `f4:l1617` | `frame.sub8_chain` | 23,410 | 0.12% |
| `f5:l1107` | `frame.add6_chain` | 22,890 | 0.12% |

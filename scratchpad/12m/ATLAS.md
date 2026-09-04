# ATLAS -- where the ops go (measured)

Built by `scratchpad/12m/atlas.py` from 8 per-op profiles of `P2-2.fjm`.
Method: every executed op is attributed to the nearest label at or below its address; that
label's name IS its macro call stack, so INCLUSIVE = ops anywhere inside a macro (the pool
size) and EXCLUSIVE = ops in that macro's own body (where a fix must land).

| profile | viewpoint | ops | coverage |
|---|---|---|---|
| P2-2.h0_0 | (589,-33,0xc0000000) | 3,485,672 | 100.000% |
| P2-2.h14_3 | (77,1503,0x40000000) | 11,653,846 | 100.000% |
| P2-2.h28_6 | (2893,1503,0x0) | 15,543,503 | 100.000% |
| P2-2.h42_9 | (2381,-289,0xc0000000) | 17,610,987 | 100.000% |
| P2-2.h57_1 | (2893,2015,0x80000000) | 19,869,492 | 100.000% |
| P2-2.h71_4 | (2637,991,0x0) | 22,733,829 | 100.000% |
| P2-2.h85_7 | (333,-33,0x40000000) | 25,876,329 | 100.000% |
| P2-2.h100_0 | (2637,991,0x40000000) | 38,832,447 | 100.000% |

The MEDIAN column below is the profile whose op count is the median of the profiled
set (`P2-2.h57_1`, 19,869,492 ops); MIN and MAX are the cheapest and dearest profiled frames. The
campaign ships on the 260-frame sweep median, so MEDIAN is the column that ranks.

## Pool table -- INCLUSIVE ops per macro (all call sites summed)

| macro | median frame | min frame | max frame | share of median |
|---|---:|---:|---:|---:|
| `hex.xor` | 8,840,657 | 1,678,111 | 16,176,827 | 44.49% |
| `hex.exact_xor` | 8,840,657 | 1,678,111 | 16,176,827 | 44.49% |
| `frame.seg_pass2_leaf_body_lines` | 7,630,345 | 2,681,250 | 18,865,331 | 38.40% |
| `frame.seg_pass1_leaf_body_ts` | 4,742,298 | 1,255 | 4,936,542 | 23.87% |
| `hex.mov` | 4,242,365 | 686,910 | 8,341,682 | 21.35% |
| `hex.zero` | 3,995,859 | 715,902 | 7,852,518 | 20.11% |
| `stream.emit_col_lines` | 3,813,734 | 509,331 | 13,119,250 | 19.19% |
| `frame.ts_step_faces` | 3,523,796 | 2 | 3,797,134 | 17.73% |
| `frame.thing_record_body` | 2,312,867 | 176,031 | 6,424,727 | 11.64% |
| `hex.address_and_variable_triple_xor` | 2,021,051 | 334,925 | 5,883,573 | 10.17% |
| `hex.triple_exact_xor` | 2,021,051 | 334,925 | 5,883,573 | 10.17% |
| `hex.pointers.set_flip_and_jump_pointers` | 2,021,051 | 334,925 | 5,883,573 | 10.17% |
| `hex.fixed_mul_lo.row` | 1,948,286 | 94,832 | 2,261,750 | 9.81% |
| `hex.fixed_mul_lo` | 1,838,566 | 14,454 | 1,988,523 | 9.25% |
| `hex.add_mul` | 1,831,530 | 89,346 | 2,122,405 | 9.22% |
| `proj.wall_x_range_m` | 1,726,861 | 29,636 | 2,042,544 | 8.69% |
| `hex.double_xor` | 1,722,967 | 277,707 | 2,825,375 | 8.67% |
| `hex.xor_zero` | 1,722,967 | 277,707 | 2,825,375 | 8.67% |
| `hex.double_exact_xor` | 1,722,967 | 277,707 | 2,825,375 | 8.67% |
| `frame.ts_piece_store` | 1,617,065 | 0 | 1,727,716 | 8.14% |
| `proj.project_thing` | 1,574,801 | 34,420 | 1,524,832 | 7.93% |
| `frame.dance_boundary` | 1,538,665 | 333,040 | 2,566,364 | 7.74% |
| `stream.steps_splice_f` | 1,432,716 | 43,372 | 1,966,009 | 7.21% |
| `stream.steps_face` | 1,380,544 | 53,492 | 1,766,345 | 6.95% |
| `frame.seg_pass1_leaf_body_lines` | 1,176,549 | 37,215 | 1,681,414 | 5.92% |
| `hex.xor_byte_from_ptr` | 1,171,111 | 193,956 | 4,846,932 | 5.89% |
| `hex.write_byte` | 1,091,598 | 81,440 | 2,004,677 | 5.49% |
| `hex.cmp` | 1,067,916 | 373,959 | 1,753,699 | 5.37% |
| `hex.write_byte_and_inc` | 1,051,940 | 6 | 1,983,906 | 5.29% |
| `proj.wall_scale_setup_m` | 1,043,845 | 112,445 | 1,755,071 | 5.25% |
| `frame.add8_chain` | 981,329 | 254,804 | 1,807,169 | 4.94% |
| `frame.lines_steps_load2` | 971,409 | 66,640 | 1,035,561 | 4.89% |
| `stream.steps_splice_c` | 912,940 | 27,862 | 816,970 | 4.59% |
| `frame.ts_piece_wr` | 895,748 | 0 | 977,719 | 4.51% |
| `frame.sub8_chain` | 873,725 | 186,291 | 913,214 | 4.40% |
| `stl.startup_and_init_all` | 837,748 | 81,783 | 1,206,406 | 4.22% |
| `hex.init` | 828,238 | 80,821 | 1,168,858 | 4.17% |
| `hex.tables.init_all` | 828,238 | 80,821 | 1,168,858 | 4.17% |
| `hex.add_constant` | 820,187 | 204,102 | 1,846,451 | 4.13% |
| `hex.scmp` | 784,143 | 167,851 | 2,813,967 | 3.95% |
| `hex.cmp.cmp_eq_next` | 781,967 | 258,894 | 1,425,337 | 3.94% |
| `hex.add.add_constant_with_leading_zeros` | 757,501 | 188,867 | 1,702,477 | 3.81% |
| `hex.add.add_hex_shifted_constant` | 757,501 | 188,867 | 1,702,477 | 3.81% |
| `hex.add_shifted` | 749,640 | 186,932 | 1,684,365 | 3.77% |
| `proj.point_to_angle` | 728,159 | 15,880 | 935,782 | 3.66% |

## Where it lands -- EXCLUSIVE ops per macro body

| macro body | median frame | share |
|---|---:|---:|
| `hex.exact_xor` | 8,840,657 | 44.49% |
| `hex.triple_exact_xor` | 2,021,051 | 10.17% |
| `hex.double_exact_xor` | 1,722,967 | 8.67% |
| `<top level: distscale>` | 785,798 | 3.95% |
| `stl.comp_if1` | 444,062 | 2.23% |
| `hex.mul.init` | 405,775 | 2.04% |
| `hex.tables.clean_table_entry__table` | 325,583 | 1.64% |
| `hex.add.clear_carry` | 304,404 | 1.53% |
| `frame.add8_chain` | 276,245 | 1.39% |
| `hex.add_mul` | 274,604 | 1.38% |
| `frame.sub8_chain` | 249,464 | 1.26% |
| `hex.if_flags` | 221,620 | 1.12% |
| `hex.pointers.xor_hex_to_flip_ptr` | 216,520 | 1.09% |
| `hex.shifts.shl_bit_once` | 194,512 | 0.98% |
| `hex.cmp` | 187,558 | 0.94% |
| `hex.mov` | 181,643 | 0.91% |
| `hex.tables.jump_to_table_entry` | 178,651 | 0.90% |
| `<top level: hex.tables.ret>` | 139,975 | 0.70% |
| `hex.shifts.shr_bit_once` | 130,378 | 0.66% |
| `<top level: hex.tables.res>` | 98,385 | 0.50% |
| `<top level: hex.add.dst>` | 93,577 | 0.47% |
| `bit.exact_xor` | 87,973 | 0.44% |
| `hex.add.init` | 87,813 | 0.44% |
| `hex.fixed_mul_lo.row` | 83,286 | 0.42% |
| `<top level: hex.mul.dst>` | 81,405 | 0.41% |
| `frame.sub4_chain` | 76,359 | 0.38% |
| `hex.mul.clear_carry` | 67,772 | 0.34% |
| `hex.pointers.read_cell_from_inners_ptrs` | 66,212 | 0.33% |
| `hex.add_constant` | 62,686 | 0.32% |
| `<top level: hex.mul.add_carry_dst>` | 60,554 | 0.30% |
| `byte.emit` | 59,218 | 0.30% |
| `frame.sub10_chain` | 54,373 | 0.27% |
| `hex.fixed_mul_lo` | 51,939 | 0.26% |
| `hex.if1` | 48,115 | 0.24% |
| `<top level: hex.pointers.to_ptr_var>` | 44,104 | 0.22% |
| `frame.add4_chain` | 43,117 | 0.22% |
| `hex.if0` | 42,961 | 0.22% |
| `<top level: hex.sub.dst>` | 42,676 | 0.21% |
| `stl.comp_if0` | 41,425 | 0.21% |
| `<top level: hex.cmp.dst>` | 33,940 | 0.17% |
| `<top level: hex.pointers.read_byte>` | 33,671 | 0.17% |
| `hex.inc.step` | 31,573 | 0.16% |
| `hex.sub.init` | 30,826 | 0.16% |
| `hex.cmp.init` | 28,737 | 0.14% |
| `<top level: hex.and.dst>` | 27,536 | 0.14% |

## THE ACTIONABLE TABLE -- per hand-written call site

The deepest call site that lies in a hand-written .fj source. Everything below it is
stl machinery that this line asked for, so this is the line that has to change.

| site | macro called | median frame | min | max | share of median |
|---|---|---:|---:|---:|---:|
| `f2:l104` | `hex.add_mul` | 1,831,530 | 89,346 | 2,122,405 | 9.22% |
| `f5:l1543` | `hex.xor` | 727,790 | 159,951 | 1,190,711 | 3.66% |
| `f5:l1542` | `hex.xor_zero` | 708,485 | 152,615 | 1,202,270 | 3.57% |
| `f8:l1090` | `w1rpat.walk` | 653,910 | 383,066 | 84,318 | 3.29% |
| `f5:l1866` | `hex.xor_byte_from_ptr` | 561,948 | 5,128 | 1,121,409 | 2.83% |
| `f8:l607` | `w1rpat.walk_win` | 543,429 | 50,200 | 841,561 | 2.73% |
| `f5:l836` | `hex.write_byte_and_inc` | 208,043 | 0 | 207,754 | 1.05% |
| `f5:l838` | `hex.write_byte_and_inc` | 197,756 | 0 | 198,291 | 1.00% |
| `f5:l837` | `hex.write_byte_and_inc` | 197,056 | 0 | 196,756 | 0.99% |
| `f5:l1569` | `hex.mov` | 193,809 | 24,267 | 297,805 | 0.98% |
| `f5:l839` | `hex.write_byte_and_inc` | 189,060 | 0 | 189,714 | 0.95% |
| `f5:l946` | `hex.scmp` | 178,684 | 0 | 210,907 | 0.90% |
| `f5:l972` | `hex.write_byte` | 178,033 | 0 | 197,394 | 0.90% |
| `f5:l1867` | `hex.ptr_inc` | 155,130 | 641 | 303,208 | 0.78% |
| `f5:l1029` | `hex.read_hex` | 147,773 | 0 | 180,710 | 0.74% |
| `f2:l86` | `hex.mov` | 134,469 | 1,769 | 154,690 | 0.68% |
| `f4:l1055` | `hex.div` | 132,213 | 28 | 207,319 | 0.67% |
| `f5:l950` | `hex.scmp` | 126,251 | 0 | 107,153 | 0.64% |
| `f2:l88` | `hex.mov` | 125,223 | 1,777 | 139,955 | 0.63% |
| `f5:l966` | `hex.scmp` | 124,826 | 0 | 110,191 | 0.63% |
| `f4:l1050` | `hex.div` | 122,673 | 8,552 | 203,316 | 0.62% |
| `f5:l895` | `hex.mov` | 121,972 | 0 | 119,194 | 0.61% |
| `f2:l90` | `hex.zero` | 119,480 | 1,512 | 138,611 | 0.60% |
| `f2:l92` | `hex.mov` | 116,273 | 1,759 | 132,735 | 0.59% |
| `f5:l1396` | `hex.read_byte` | 110,473 | 2,400 | 269,784 | 0.56% |
| `f5:l2331` | `hex.read_hex` | 103,091 | 74,268 | 128,230 | 0.52% |
| `f8:l1006` | `hex.read_byte_and_inc` | 102,872 | 1,280 | 834,467 | 0.52% |
| `f5:l1544` | `hex.xor` | 102,390 | 20,474 | 173,383 | 0.52% |
| `f5:l1221` | `hex.write_byte_and_inc` | 93,456 | 0 | 93,296 | 0.47% |
| `f5:l458` | `hex.scmp` | 87,024 | 86,719 | 86,987 | 0.44% |
| `f8:l893` | `w1rpat.walk_win` | 86,243 | 0 | 381,317 | 0.43% |
| `f5:l2563` | `hex.write_hex_and_inc` | 83,576 | 81,698 | 84,012 | 0.42% |
| `f5:l1572` | `hex.shl_hex` | 83,441 | 10,356 | 123,191 | 0.42% |
| `f5:l1571` | `hex.shr_bit` | 81,953 | 11,570 | 126,528 | 0.41% |
| `f5:l1573` | `frame.add8_chain` | 79,347 | 14,515 | 122,860 | 0.40% |
| `f5:l1033` | `hex.read_byte` | 77,482 | 0 | 112,641 | 0.39% |
| `f5:l1920` | `hex.read_byte` | 75,707 | 54,295 | 76,926 | 0.38% |
| `f8:l1008` | `hex.read_byte_and_inc` | 75,455 | 0 | 734,109 | 0.38% |
| `f5:l1292` | `hex.add` | 71,598 | 0 | 81,434 | 0.36% |
| `f5:l1945` | `hex.mov` | 71,483 | 0 | 73,571 | 0.36% |
| `f5:l1214` | `hex.read_byte` | 67,046 | 0 | 72,625 | 0.34% |
| `f5:l2097` | `hex.read_byte` | 65,214 | 74,975 | 65,376 | 0.33% |
| `f5:l1281` | `hex.add` | 65,015 | 0 | 58,118 | 0.33% |
| `f5:l2029` | `hex.read_byte` | 63,994 | 62,303 | 72,154 | 0.32% |
| `f4:l1641` | `hex.scmp` | 63,702 | 67,996 | 63,420 | 0.32% |

## Per call SITE -- the innermost (caller file:line -> macro) pairs

f<i> is the i-th file passed to the assembler: f1=fj_consts, f2=fixed_point, f3=present, f4=projection, f5=frame_render, f6=plane_render, f7=plane_bands, f8=stream_render, f9=e1m1_00_entry, f10=e1m1_01_tables, f11=e1m1_02_main, f12=e1m1_03_segconsts, f13=e1m1_04_walk, f14=e1m1_05_state, f15=e1m1_06_banks

| site | macro | median frame | share |
|---|---|---:|---:|
| `s16:l12` | `hex.exact_xor` | 8,840,657 | 44.49% |
| `s16:l217` | `hex.triple_exact_xor` | 2,021,051 | 10.17% |
| `s16:l77` | `hex.double_exact_xor` | 1,722,967 | 8.67% |
| `s15:l65` | `stl.comp_if1` | 444,062 | 2.23% |
| `s21:l32` | `hex.mul.init` | 405,775 | 2.04% |
| `s21:l61` | `hex.tables.clean_table_entry__table` | 275,087 | 1.38% |
| `s24:l26` | `hex.add_mul` | 274,604 | 1.38% |
| `s27:l107` | `hex.pointers.xor_hex_to_flip_ptr` | 207,560 | 1.04% |
| `s19:l10` | `hex.shifts.shl_bit_once` | 169,900 | 0.86% |
| `s17:l13` | `hex.tables.jump_to_table_entry` | 163,202 | 0.82% |
| `s20:l32` | `hex.if_flags` | 139,980 | 0.70% |
| `s20:l128` | `hex.cmp` | 122,453 | 0.62% |
| `s17:l33` | `hex.add.clear_carry` | 109,897 | 0.55% |
| `s19:l19` | `hex.shifts.shr_bit_once` | 102,315 | 0.51% |
| `s17:l31` | `hex.add.clear_carry` | 92,837 | 0.47% |
| `s5:l9` | `bit.exact_xor` | 87,973 | 0.44% |
| `s21:l34` | `hex.add.init` | 87,813 | 0.44% |
| `s24:l92` | `hex.add.clear_carry` | 81,589 | 0.41% |
| `f5:l1573` | `frame.add8_chain` | 79,347 | 0.40% |
| `s28:l45` | `hex.pointers.read_cell_from_inners_ptrs` | 66,212 | 0.33% |
| `s20:l122` | `hex.cmp` | 65,105 | 0.33% |
| `s24:l24` | `hex.mul.clear_carry` | 64,630 | 0.33% |
| `f2:l91` | `hex.fixed_mul_lo.row` | 46,875 | 0.24% |
| `f4:l239` | `frame.add8_chain` | 43,573 | 0.22% |
| `s20:l49` | `hex.if1` | 43,384 | 0.22% |
| `f5:l913` | `frame.sub8_chain` | 32,592 | 0.16% |
| `s21:l35` | `hex.sub.init` | 30,826 | 0.16% |
| `s21:l33` | `hex.cmp.init` | 28,737 | 0.14% |
| `f5:l915` | `frame.sub8_chain` | 28,539 | 0.14% |
| `s19:l18` | `hex.shifts.shr_bit_once` | 28,063 | 0.14% |
| `s19:l35` | `stl.comp_if0` | 27,687 | 0.14% |
| `f4:l1714` | `frame.sub10_chain` | 27,367 | 0.14% |
| `f4:l1716` | `frame.sub10_chain` | 27,006 | 0.14% |
| `s32:l10` | `hex.add_constant` | 26,964 | 0.14% |
| `f5:l918` | `frame.sub8_chain` | 26,521 | 0.13% |
| `f10:l108457` | `byte.init` | 26,500 | 0.13% |
| `f5:l1872` | `frame.add8_chain` | 25,305 | 0.13% |
| `f10:l190398` | `cm.init` | 24,740 | 0.12% |
| `s19:l9` | `hex.shifts.shl_bit_once` | 24,612 | 0.12% |
| `f4:l1628` | `frame.sub8_chain` | 23,840 | 0.12% |
| `s17:l62` | `hex.add_shifted` | 23,766 | 0.12% |
| `f4:l1617` | `frame.sub8_chain` | 23,250 | 0.12% |
| `f5:l1104` | `frame.add6_chain` | 22,890 | 0.12% |
| `f5:l1871` | `frame.add8_chain` | 22,820 | 0.11% |
| `s20:l212` | `hex.mov` | 22,131 | 0.11% |

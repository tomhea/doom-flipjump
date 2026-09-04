# ATLAS -- where the ops go (measured)

Built by `scratchpad/12m/atlas.py` from 8 per-op profiles of `BASE.fjm`.
Method: every executed op is attributed to the nearest label at or below its address; that
label's name IS its macro call stack, so INCLUSIVE = ops anywhere inside a macro (the pool
size) and EXCLUSIVE = ops in that macro's own body (where a fix must land).

| profile | viewpoint | ops | coverage |
|---|---|---|---|
| BASE.h0_0 | (589,-33,0xc0000000) | 3,670,504 | 100.000% |
| BASE.h14_3 | (77,1503,0x40000000) | 11,897,081 | 100.000% |
| BASE.h28_6 | (2893,1503,0x0) | 15,805,821 | 100.000% |
| BASE.h42_9 | (2381,-289,0xc0000000) | 17,969,148 | 100.000% |
| BASE.h57_1 | (2893,2015,0x80000000) | 20,204,970 | 100.000% |
| BASE.h71_4 | (2637,991,0x0) | 23,112,749 | 100.000% |
| BASE.h85_7 | (333,-33,0x40000000) | 26,189,935 | 100.000% |
| BASE.h100_0 | (2637,991,0x40000000) | 39,514,873 | 100.000% |

The MEDIAN column below is the profile whose op count is the median of the profiled
set (`BASE.h57_1`, 20,204,970 ops); MIN and MAX are the cheapest and dearest profiled frames. The
campaign ships on the 260-frame sweep median, so MEDIAN is the column that ranks.

## Pool table -- INCLUSIVE ops per macro (all call sites summed)

| macro | median frame | min frame | max frame | share of median |
|---|---:|---:|---:|---:|
| `hex.exact_xor` | 8,888,487 | 1,830,827 | 16,372,862 | 43.99% |
| `hex.xor` | 8,888,487 | 1,830,827 | 16,372,862 | 43.99% |
| `frame.seg_pass2_leaf_body_lines` | 7,865,735 | 2,913,382 | 19,296,802 | 38.93% |
| `frame.seg_pass1_leaf_body_ts` | 4,762,279 | 1,772 | 4,964,298 | 23.57% |
| `hex.mov` | 4,215,705 | 770,222 | 8,341,122 | 20.86% |
| `hex.zero` | 4,147,979 | 842,541 | 8,026,643 | 20.53% |
| `stream.emit_col_lines` | 3,812,820 | 514,621 | 13,298,419 | 18.87% |
| `frame.ts_step_faces` | 3,563,542 | 322 | 3,842,058 | 17.64% |
| `frame.thing_record_body` | 2,383,571 | 138,612 | 6,739,479 | 11.80% |
| `hex.pointers.set_flip_and_jump_pointers` | 2,022,344 | 321,940 | 5,883,299 | 10.01% |
| `hex.address_and_variable_triple_xor` | 2,022,344 | 321,940 | 5,883,299 | 10.01% |
| `hex.triple_exact_xor` | 2,022,344 | 321,940 | 5,883,299 | 10.01% |
| `hex.fixed_mul_lo.row` | 1,951,087 | 110,712 | 2,224,516 | 9.66% |
| `hex.fixed_mul_lo` | 1,878,446 | 15,227 | 1,985,935 | 9.30% |
| `hex.add_mul` | 1,832,124 | 105,421 | 2,081,047 | 9.07% |
| `hex.xor_zero` | 1,817,023 | 319,161 | 3,030,235 | 8.99% |
| `hex.double_exact_xor` | 1,817,023 | 319,161 | 3,030,235 | 8.99% |
| `hex.double_xor` | 1,817,023 | 319,161 | 3,030,235 | 8.99% |
| `proj.wall_x_range_m` | 1,708,501 | 29,551 | 2,027,279 | 8.46% |
| `proj.project_thing` | 1,640,613 | 126,236 | 1,579,853 | 8.12% |
| `frame.ts_piece_store` | 1,632,509 | 0 | 1,744,518 | 8.08% |
| `stream.steps_splice_f` | 1,399,969 | 43,581 | 1,982,666 | 6.93% |
| `stream.steps_face` | 1,382,386 | 51,868 | 1,796,142 | 6.84% |
| `frame.dance_boundary` | 1,290,578 | 272,651 | 2,095,172 | 6.39% |
| `hex.xor_byte_from_ptr` | 1,166,898 | 190,908 | 4,847,419 | 5.78% |
| `frame.seg_pass1_leaf_body_lines` | 1,142,847 | 37,986 | 1,675,069 | 5.66% |
| `hex.write_byte` | 1,106,061 | 80,960 | 2,015,171 | 5.47% |
| `proj.wall_scale_setup_m` | 1,072,631 | 145,232 | 1,784,256 | 5.31% |
| `hex.write_byte_and_inc` | 1,066,079 | 0 | 1,998,546 | 5.28% |
| `hex.cmp` | 1,041,872 | 389,431 | 1,726,889 | 5.16% |
| `stream.steps_splice_c` | 940,088 | 26,809 | 814,719 | 4.65% |
| `frame.lines_steps_load2` | 934,576 | 78,019 | 995,576 | 4.63% |
| `frame.ts_piece_wr` | 911,089 | 0 | 993,108 | 4.51% |
| `hex.ptr_index` | 909,630 | 87,007 | 2,376,507 | 4.50% |
| `frame.sub8_chain` | 879,645 | 166,845 | 937,841 | 4.35% |
| `hex.add` | 854,072 | 107,975 | 2,047,474 | 4.23% |
| `hex.scmp` | 852,998 | 225,793 | 2,877,315 | 4.22% |
| `stl.startup_and_init_all` | 839,580 | 82,743 | 1,206,913 | 4.16% |
| `hex.add_constant` | 839,003 | 216,081 | 1,865,337 | 4.15% |
| `hex.tables.jump_to_table_entry` | 834,330 | 105,926 | 1,969,625 | 4.13% |
| `hex.tables.init_all` | 830,070 | 81,781 | 1,169,365 | 4.11% |
| `hex.init` | 830,070 | 81,781 | 1,169,365 | 4.11% |
| `hex.add.add_hex_shifted_constant` | 780,787 | 203,141 | 1,722,925 | 3.86% |
| `hex.add.add_constant_with_leading_zeros` | 780,787 | 203,141 | 1,722,925 | 3.86% |
| `hex.add_shifted` | 772,926 | 201,206 | 1,704,813 | 3.83% |

## Where it lands -- EXCLUSIVE ops per macro body

| macro body | median frame | share |
|---|---:|---:|
| `hex.exact_xor` | 8,888,487 | 43.99% |
| `hex.triple_exact_xor` | 2,022,344 | 10.01% |
| `hex.double_exact_xor` | 1,817,023 | 8.99% |
| `<top level: distscale>` | 824,844 | 4.08% |
| `stl.comp_if1` | 458,588 | 2.27% |
| `hex.mul.init` | 406,197 | 2.01% |
| `hex.add.clear_carry` | 330,711 | 1.64% |
| `hex.tables.clean_table_entry__table` | 328,031 | 1.62% |
| `hex.add_mul` | 274,520 | 1.36% |
| `frame.sub8_chain` | 253,036 | 1.25% |
| `hex.tables.jump_to_table_entry` | 249,922 | 1.24% |
| `hex.shifts.shr_bit_once` | 227,026 | 1.12% |
| `hex.if_flags` | 221,620 | 1.10% |
| `hex.pointers.xor_hex_to_flip_ptr` | 216,015 | 1.07% |
| `hex.shifts.shl_bit_once` | 201,639 | 1.00% |
| `frame.add8_chain` | 192,803 | 0.95% |
| `hex.cmp` | 189,360 | 0.94% |
| `hex.mov` | 182,040 | 0.90% |
| `<top level: hex.tables.ret>` | 140,455 | 0.70% |
| `<top level: hex.tables.res>` | 98,385 | 0.49% |
| `<top level: hex.add.dst>` | 93,092 | 0.46% |
| `bit.exact_xor` | 88,247 | 0.44% |
| `hex.add.init` | 88,091 | 0.44% |
| `hex.fixed_mul_lo.row` | 85,493 | 0.42% |
| `<top level: hex.mul.dst>` | 81,405 | 0.40% |
| `hex.mul.clear_carry` | 69,864 | 0.35% |
| `hex.pointers.read_cell_from_inners_ptrs` | 66,201 | 0.33% |
| `frame.sub4_chain` | 64,122 | 0.32% |
| `<top level: hex.mul.add_carry_dst>` | 60,554 | 0.30% |
| `hex.add_constant` | 58,216 | 0.29% |
| `byte.emit` | 54,404 | 0.27% |
| `stl.comp_if0` | 53,386 | 0.26% |
| `hex.fixed_mul_lo` | 51,947 | 0.26% |
| `frame.sub10_chain` | 51,915 | 0.26% |
| `hex.if1` | 51,704 | 0.26% |
| `hex.if0` | 48,356 | 0.24% |
| `<top level: hex.pointers.to_ptr_var>` | 44,104 | 0.22% |
| `<top level: hex.sub.dst>` | 42,676 | 0.21% |
| `frame.add4_chain` | 40,493 | 0.20% |
| `<top level: hex.cmp.dst>` | 34,353 | 0.17% |
| `<top level: hex.pointers.read_byte>` | 33,671 | 0.17% |
| `hex.sub.init` | 30,826 | 0.15% |
| `hex.cmp.init` | 29,217 | 0.14% |
| `frame.sub2_chain` | 28,470 | 0.14% |
| `<top level: hex.and.dst>` | 27,424 | 0.14% |

## THE ACTIONABLE TABLE -- per hand-written call site

The deepest call site that lies in a hand-written .fj source. Everything below it is
stl machinery that this line asked for, so this is the line that has to change.

| site | macro called | median frame | min | max | share of median |
|---|---|---:|---:|---:|---:|
| `f2:l104` | `hex.add_mul` | 1,832,124 | 105,421 | 2,081,047 | 9.07% |
| `f8:l1090` | `w1rpat.walk` | 655,605 | 386,861 | 83,624 | 3.24% |
| `f5:l1519` | `hex.xor` | 602,501 | 124,330 | 960,693 | 2.98% |
| `f5:l1518` | `hex.xor_zero` | 596,136 | 128,026 | 989,684 | 2.95% |
| `f5:l1798` | `hex.xor_byte_from_ptr` | 564,334 | 5,128 | 1,113,401 | 2.79% |
| `f8:l607` | `w1rpat.walk_win` | 516,001 | 39,421 | 761,298 | 2.55% |
| `f5:l1371` | `hex.ptr_index` | 357,065 | 9,106 | 367,426 | 1.77% |
| `f5:l816` | `hex.write_byte_and_inc` | 208,772 | 0 | 208,483 | 1.03% |
| `f5:l818` | `hex.write_byte_and_inc` | 197,923 | 0 | 198,459 | 0.98% |
| `f5:l817` | `hex.write_byte_and_inc` | 196,416 | 0 | 196,116 | 0.97% |
| `f5:l819` | `hex.write_byte_and_inc` | 192,520 | 0 | 193,275 | 0.95% |
| `f5:l952` | `hex.write_byte` | 179,499 | 0 | 199,368 | 0.89% |
| `f5:l926` | `hex.scmp` | 177,604 | 0 | 209,585 | 0.88% |
| `f5:l1799` | `hex.ptr_inc` | 153,386 | 481 | 299,019 | 0.76% |
| `f5:l1009` | `hex.read_hex` | 147,687 | 0 | 180,347 | 0.73% |
| `f5:l451` | `hex.scmp` | 143,344 | 143,039 | 143,307 | 0.71% |
| `f4:l1048` | `hex.div` | 135,175 | 1,554 | 216,735 | 0.67% |
| `f2:l86` | `hex.mov` | 130,441 | 1,703 | 149,503 | 0.65% |
| `f2:l92` | `hex.mov` | 127,547 | 2,581 | 141,635 | 0.63% |
| `f5:l930` | `hex.scmp` | 125,693 | 0 | 106,368 | 0.62% |
| `f5:l946` | `hex.scmp` | 124,596 | 0 | 109,962 | 0.62% |
| `f2:l88` | `hex.mov` | 123,127 | 1,849 | 141,694 | 0.61% |
| `f4:l1043` | `hex.div` | 122,277 | 10,114 | 200,808 | 0.61% |
| `f2:l90` | `hex.zero` | 121,818 | 1,434 | 136,054 | 0.60% |
| `f5:l875` | `hex.mov` | 119,057 | 0 | 116,227 | 0.59% |
| `f5:l1372` | `hex.read_byte` | 103,136 | 2,400 | 271,715 | 0.51% |
| `f8:l1006` | `hex.read_byte_and_inc` | 101,592 | 1,600 | 798,229 | 0.50% |
| `f5:l1201` | `hex.write_byte_and_inc` | 92,748 | 0 | 92,588 | 0.46% |
| `f5:l1520` | `hex.xor` | 91,941 | 20,295 | 144,795 | 0.46% |
| `f5:l2256` | `hex.read_hex` | 89,901 | 70,908 | 106,385 | 0.44% |
| `f5:l1852` | `hex.read_byte` | 89,076 | 63,006 | 89,427 | 0.44% |
| `f8:l893` | `w1rpat.walk_win` | 85,463 | 0 | 383,311 | 0.42% |
| `f5:l2488` | `hex.write_hex_and_inc` | 83,946 | 82,436 | 84,430 | 0.42% |
| `f8:l1008` | `hex.read_byte_and_inc` | 81,911 | 0 | 738,125 | 0.41% |
| `f5:l1013` | `hex.read_byte` | 74,627 | 0 | 109,110 | 0.37% |
| `f5:l1272` | `hex.add` | 72,702 | 0 | 81,532 | 0.36% |
| `f4:l1624` | `hex.scmp` | 68,983 | 71,197 | 68,701 | 0.34% |
| `f5:l1194` | `hex.read_byte` | 65,766 | 0 | 71,241 | 0.33% |
| `f5:l1261` | `hex.add` | 64,649 | 0 | 58,308 | 0.32% |
| `f4:l1698` | `hex.mov` | 64,546 | 7,355 | 78,960 | 0.32% |
| `f5:l2029` | `hex.read_byte` | 62,867 | 74,890 | 63,029 | 0.31% |
| `f8:l1016` | `hex.scmp` | 62,525 | 0 | 606,272 | 0.31% |
| `f4:l1696` | `hex.mov` | 61,665 | 6,599 | 74,641 | 0.31% |
| `f5:l2180` | `hex.read_hex` | 60,454 | 2,196 | 107,810 | 0.30% |
| `f4:l1609` | `hex.mov` | 59,742 | 58,720 | 59,814 | 0.30% |

## Per call SITE -- the innermost (caller file:line -> macro) pairs

f<i> is the i-th file passed to the assembler: f1=fj_consts, f2=fixed_point, f3=present, f4=projection, f5=frame_render, f6=plane_render, f7=plane_bands, f8=stream_render, f9=00_entry, f10=01_tables, f11=02_main, f12=03_segconsts, f13=04_walk, f14=05_state, f15=06_banks

| site | macro | median frame | share |
|---|---|---:|---:|
| `s16:l12` | `hex.exact_xor` | 8,888,487 | 43.99% |
| `s16:l217` | `hex.triple_exact_xor` | 2,022,344 | 10.01% |
| `s16:l77` | `hex.double_exact_xor` | 1,817,023 | 8.99% |
| `s15:l65` | `stl.comp_if1` | 458,588 | 2.27% |
| `s21:l32` | `hex.mul.init` | 406,197 | 2.01% |
| `s21:l61` | `hex.tables.clean_table_entry__table` | 275,739 | 1.36% |
| `s24:l26` | `hex.add_mul` | 274,520 | 1.36% |
| `s17:l13` | `hex.tables.jump_to_table_entry` | 234,616 | 1.16% |
| `s27:l107` | `hex.pointers.xor_hex_to_flip_ptr` | 207,055 | 1.02% |
| `s19:l19` | `hex.shifts.shr_bit_once` | 196,430 | 0.97% |
| `s19:l10` | `hex.shifts.shl_bit_once` | 176,938 | 0.88% |
| `s20:l32` | `hex.if_flags` | 139,980 | 0.69% |
| `s20:l128` | `hex.cmp` | 125,719 | 0.62% |
| `s17:l33` | `hex.add.clear_carry` | 115,941 | 0.57% |
| `s17:l31` | `hex.add.clear_carry` | 96,105 | 0.48% |
| `s5:l9` | `bit.exact_xor` | 88,247 | 0.44% |
| `s21:l34` | `hex.add.init` | 88,091 | 0.44% |
| `s24:l92` | `hex.add.clear_carry` | 80,911 | 0.40% |
| `s24:l24` | `hex.mul.clear_carry` | 66,722 | 0.33% |
| `s28:l45` | `hex.pointers.read_cell_from_inners_ptrs` | 66,201 | 0.33% |
| `s20:l122` | `hex.cmp` | 63,641 | 0.31% |
| `f2:l91` | `hex.fixed_mul_lo.row` | 48,832 | 0.24% |
| `s20:l49` | `hex.if1` | 47,497 | 0.24% |
| `f4:l239` | `frame.add8_chain` | 45,297 | 0.22% |
| `s19:l35` | `stl.comp_if0` | 33,068 | 0.16% |
| `f5:l893` | `frame.sub8_chain` | 32,802 | 0.16% |
| `s21:l35` | `hex.sub.init` | 30,826 | 0.15% |
| `s19:l18` | `hex.shifts.shr_bit_once` | 30,596 | 0.15% |
| `s21:l33` | `hex.cmp.init` | 29,217 | 0.14% |
| `f5:l895` | `frame.sub8_chain` | 28,711 | 0.14% |
| `f5:l898` | `frame.sub8_chain` | 27,771 | 0.14% |
| `s32:l10` | `hex.add_constant` | 27,281 | 0.14% |
| `s17:l62` | `hex.add_shifted` | 26,620 | 0.13% |
| `f10:l108457` | `byte.init` | 26,500 | 0.13% |
| `f4:l1610` | `frame.sub8_chain` | 26,273 | 0.13% |
| `f4:l1699` | `frame.sub10_chain` | 26,011 | 0.13% |
| `f4:l1697` | `frame.sub10_chain` | 25,904 | 0.13% |
| `f5:l1804` | `frame.add8_chain` | 25,468 | 0.13% |
| `f10:l190398` | `cm.init` | 24,740 | 0.12% |
| `s19:l9` | `hex.shifts.shl_bit_once` | 24,701 | 0.12% |
| `f4:l1614` | `frame.sub8_chain` | 23,520 | 0.12% |
| `f5:l1084` | `frame.add6_chain` | 22,890 | 0.11% |
| `f5:l1803` | `frame.add8_chain` | 22,820 | 0.11% |
| `f2:l118` | `hex.fixed_mul_lo.row` | 21,839 | 0.11% |
| `s20:l212` | `hex.mov` | 21,441 | 0.11% |

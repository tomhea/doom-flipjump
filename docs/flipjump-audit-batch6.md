# Whole-stl audit, batch 6 (the last): screen.fj + the cross-cutting checks (origin/1.6.0 = 287f28b)

Reviewed at 287f28b in the read-only worktree C:/Users/tomhe/Documents/flipjump-audit2 (its `_fjcore.pyd` is
287f28b's; `git status` clean before and after). No repo file was changed. Every run went through
`heavy.py audit6 --light`, one at a time.

## Tools (all in this folder; each has its R9 control)

| tool | what | control |
|---|---|---|
| `../../check/cxm.py` | the measurement (T, S, the address-valued wflips) | `--selftest` PASS (`cxm_selftest.log`) |
| `m6specs.py` | batch 6's cxm specs: all 13 screen macros, `output_bits` n = 0..64, `define_palette` at 10 formats x 1/2/16 entries, `set_window_title` 0..40 bytes, `end_frame` at every C boundary x used_bits 0/3, `end_command` | `--check` compares each row with the device format's exact bit count |
| `edge6.py` | the screen macros against the REAL device (`InMemoryScreen`, as the tests run them): 78 POS cases (must work) and 34 VIOL cases (a precondition broken: what happens), at w=64 and w=32 | `--selftest`: a wrong palette value, swapped icon sides and a device error must all FAIL (PASS, `edge_selftest.log`) |
| `w16.py` | two screen programs at w=16 | - |
| `ident6.py` | the guard fix's identity: in-range programs assemble to the same .fjm with both stls | a program one `present` longer must differ (it does) |
| `mutants6.py` | screen mutants on `mtree/` (batch 5's 287f28b copy + engine) against `tests/unit/test_stl_devices.py` (the only test reaching a screen macro), and `--edge` against edge6's POS cases | two CTRL mutants, both caught |
| `xcut.py` | the cross-cutting parser: every `def` (402, = `grep -c "^\s*def "`), its doc block, signature, `<` externs, `>` exports, body; the call graph (cgraph.py's); the test corpus (1238 texts: every compile-table program, every `tests/**/*.fj`, the fj inside `tests/unit/*.py`) | `--selftest` (a known snippet) |
| `cxstyle.py`, `cxnames.py`, `readmes.py`, `claimcalls.py`, `xpath.py`, `gen_lists.py` | (d3) style, (d3) undefined names, (c), (b) alias calls, a dependency-path printer, the lists | `--selftest` on cxstyle / cxnames / readmes |

# Part 1: `flipjump/stl/screen.fj` (13 defs)

## The device format, macro by macro

Every macro emits exactly the README's / ScreenIO's command: the measured bits equal the format's bit count at w=64
and w=32 (`m_SCR_w64_check.log`, `m_SCR_w32_check.log`: ALL EXACT, 68 rows each), and every POS case parses on
`InMemoryScreen` into the expected state (`edge_screen.log`: 78/78 at w=64 and at w=32; `w16.log`: 2/2 at w=16).

| macro | emits | device checks that passed |
|---|---|---|
| `output_bits n, value` | the n low bits, lsb first | n = 0, 1, 7, 16, 64 exact |
| `init_screen` | `01 w:16 h:16 format:8` | w 1 .. 65534 (with end_frame at every C), h up to 252 with a full-column fill; a second init_screen (the life cycle: the title kept, the frame counted) |
| `define_palette` | `02 slot:8 first:B last:B` + 3 bytes an entry + the pad | formats 1, 2, 6, 7, 9, 12, 15, 16 at [1,2], [top,top], [0,0]; 256 entries at format 8 (a 768-byte constant); the pad `(8-(2*format)%8)%8` is right at every format (16+2B+24k bits round up to 24k + 8*ceil(B/4) + 16) |
| `select_palette`, `builtin_palette` | `06 slot`, `07 slot id` | slot 255, id 4 at format 5 |
| `set_max_fps` | `03 fps` | 0, 1, 255 |
| `set_window_title` | `04` the bytes `00` | the literal "DOOM", empty (0), a UTF-8 title with 2- and 3-byte characters given as a number |
| `set_window_icon_header` | `05 w h` | 2 x 3 (w != h); 255 x 1 at B = 3 with `end_command 0, 765` as the padding |
| `draw_raw`, `draw_collines`, `present` | `10`, `11`, `1F` | draw_raw at B = 3 and 24 |
| `end_frame width, used_bits` | END_CMD (C one-bits), the pad, `1F` | widths 1, 14, 15, 254, 255, 4094, 4095 (and 65534 with h = 1); used_bits 0..7 (one record of 12 + B bits, B = 1..8) |
| `end_command c, used_bits` | c one-bits, the pad | c = 4, 8, 12, 16 x used 0 / 5; c = 0 as a pure pad |

**Every device command has a macro, or a documented reason it doesn't:** 0x01, 0x02, 0x03, 0x04, 0x06, 0x07 and 0x1F
fully; 0x05 and 0x10 as headers ("the colours ... are the program's own output"); 0x11 as `draw_collines` +
`end_frame` / `end_command` (the column records are run-time output). 0x00 is reserved (no macro, right). The
`_extension_command` hook is "not part of the wire API". The one gap: nothing names how to emit the zero bits after
draw_raw's or the icon's colours; `end_command 0, used_bits` does it (verified), undocumented (M4).

**hex.hex clamps, vec wraps: which does screen.fj rely on?** Neither. Every field goes out through
`stl.output_char` (runlib.fj:203, "outputs the byte (ascii & 0xff)") or `screen.output_bits` ("the n low bits"), so an
out-of-range constant WRAPS modulo 2^field, silently (M1).

## BLOCKING

None. No in-range input gives a wrong command, and every Complexity line is exact.

## MINOR

### M1. Out-of-range constants wrap silently into a different, VALID command (screen.fj:20, :31, :43, :51, :60, :79)

The docs give the ranges of init_screen and the icon only; define_palette's `slot` / `first` / `last`, select_palette's
and builtin_palette's `slot`, and `fps` have none. Reproducer: `edge6.py <stl> 64 32`, the VIOL lines of
`edge_screen.log` (the same at w=32):

| call | what the device gets |
|---|---|
| `define_palette 8, 256, 0, 0, 0x332211` | **slot 0 redefined** (the default palette's entry 0 becomes (17,34,51)), no error |
| `define_palette 4, 1, 16, 16, rgb` (format 4) | entry **0** of slot 1 set; `17, 17` sets entry 1 |
| `define_palette 4, 1, 0, 16, rgb` | last = 0, then 16 entries' bytes parsed as commands: "unknown (0x30)" |
| `init_screen 65541, 1, 1` / `init_screen 1, 1, 264` | a **5 x 1** screen / format **8**, no error |
| `select_palette 256`, `builtin_palette 257, 2`, `builtin_palette 1, 260` | slot 0, slot 1, id **4**, no error |
| `set_max_fps 300` | fps **44** |
| `set_window_icon_header 257, 1` | a 1 x 1 icon |

(`init_screen 65535`, `0`, h `65532`, format `0`, icon side 0 / 256 and `builtin id 5` are refused by the device with
its message.)

**Smallest fix, doc-only:** a range clause on each: "slot 0..255", "0 <= first <= last < 2^format", "fps 0..255".

**Recommended fix (correctness first; zero ops, no image change): assemble-time guards**, the stl's own idiom
(basic_pointers.fj:27-32, `rep(cond, i) .an_undefined_macro_named_for_the_rule`). 10 lines, prototyped in
`fix/flipjump/stl/screen.fj`:

```
init_screen:      rep(width < 1 || width > 65534, i) .init_screen__width_must_be_1_to_65534
                  rep(height < 1 || height > 65531, i) .init_screen__height_must_be_1_to_65531
                  rep((format < 1 || format > 16) && format != 24, i) .init_screen__format_must_be_1_to_16_or_24
define_palette:   rep(slot < 0 || slot > 255, i) .define_palette__slot_must_be_0_to_255
                  rep(first < 0 || first > last || last >= 1<<format, i) .define_palette__need_0_le_first_le_last_below_2_pow_format
select_palette:   rep(slot < 0 || slot > 255, i) .select_palette__slot_must_be_0_to_255
builtin_palette:  rep(slot < 0 || slot > 255, i) .builtin_palette__slot_must_be_0_to_255
                  rep(id < 0 || id > 4, i) .builtin_palette__id_must_be_0_to_4
set_max_fps:      rep(fps < 0 || fps > 255, i) .set_max_fps__fps_must_be_0_to_255
icon_header:      rep(width < 1 || width > 255 || height < 1 || height > 255, i) .set_window_icon_header__sides_must_be_1_to_255
```

Verified: `fix_ident.log` - a program using every macro in range (w 1 / 4 / 160 / 65534, h up to 65531, formats 1, 4,
8, 16, 24, slots 0 / 7 / 255, ...) is **byte-identical** to 287f28b's at w=64 and w=32 (control: one more `present`
differs); `fix_edge.log` - all 78 POS cases still pass, and every silent row above (and every device-refused one) is
now an assembly error that names the rule ("macro screen.define_palette__slot_must_be_0_to_255 is used but isn't
defined", `probe_msg.log`). Tests to add with it: one `pytest.raises` a guard (edge6's VIOL bodies), plus the mutant
tests below.

### M2. `set_window_title text` (screen.fj:65-72): three undocumented rules about `text`

- **No 0 byte inside.** The device ends the title at the first 0 and parses the rest as commands:
  `set_window_title "ab\0cd"` (or `"ab\x00cd"`) -> "ScreenIO: unknown (0x63) at output byte 10" (`probe_title.log`).
- **UTF-8, spelled as bytes.** A fj string literal holds only printable ASCII and `\xNN` escapes (fj_parser.py:161-171;
  a non-ASCII character in a literal is a lexing error), so a non-ASCII title is its UTF-8 bytes: `"\xc3\xa9"` gives
  e-acute; the Latin-1 `"\xe9"` gives "title byte 0 (0xE9) is not valid UTF-8".
- **Top 0 bytes vanish:** stl.output stops at the top non-zero byte (`((#str)+7)>>3`), so `0x006261` gives "ab".
  Harmless; it is why a trailing "\0" cannot be sent.

Fix (doc, 1 line): "text is a constant string of UTF-8 bytes with no 0 byte (a non-ASCII character as its \xNN bytes);
it is sent up to its top non-zero byte." And define `string_length` there (`((#text)+7)/8` bytes): it is not a
parameter (the same in runlib.fj:207's stl.output).

### M3. `define_palette` (screen.fj:27-30): undocumented

- **rgb's length**: bytes beyond 3(last-first+1) are dropped; missing ones are 0, so those entries are silently black
  (`define_palette 8, 1, 0, 1, 0x332211`: entry 1 = (0,0,0)). Say: "rgb holds 3(last-first+1) bytes; missing ones are 0
  (black)".
- "format is init_screen's" is said; a different one misparses ("output ended inside define_palette", edge VIOL).
- The Complexity note `24(last-first+1)  (+ the padding to the byte)` (rev 7, owner-reviewed, Rule A: 2format+16 is 11%
  at size 16) reads as if the padding were the only other term; measured exactly 24k + 8*ceil(format/4) + 16
  (`m_SCR_*`). The line STANDS by the conventions; only its parenthetical could say "(+ 8*ceil(format/4) + 16: the
  header and the padding)". Not a front-line row.

### M4. `end_command 0, used_bits` as "zero bits to the byte" is undocumented (screen.fj:108-113)

draw_raw's and the icon's colours end with zero bits to the byte, the program's own output; nothing says how.
`end_command 0, used_bits` emits exactly that (edge POS "draw_raw f=3 ... end_command 0, 9" and the 255 x 1 icon both
parse). Fix (doc): "c = 0 outputs only the zero bits to the byte (e.g. after draw_raw's or the icon's colours)".

### M5. (the device, not the stl) `InMemoryScreen` allocates w x h at init_screen (ScreenIO.py:446)

`pixel_indices = [0] * (width * height)`: a legal `init_screen 65534, 65531, f` asks for a 4.3e9-element list (~34 GB).
Seen in this audit: under the CTRL mutant (bits msb-first) an init_screen became a huge screen and the edge6 child
reached 8.6 GB before I stopped it (my own process; the mutant tree was restored by the runner). A headless run of a
legal max-size screen cannot work. Not a screen.fj bug; for the device owner (refuse above a size, or a lazy picture).

## Complexity lines (screen.fj) against the measurement

All 13 are exact in time AND space (no wflips: one op a bit), at w=64 and w=32 (`m_SCR_w64_check.log`): output_bits n;
init_screen 48; select_palette 16; builtin_palette 24; set_max_fps 16; set_window_title 8(L+2) at L = 0, 1, 5, 16,
40; the icon header 24; draw_raw / draw_collines / present 8; end_frame C + pad + 8 at every C x used 0 / 3;
end_command c + pad. define_palette: measured 24k + 8*ceil(B/4) + 16 (B = 1..16, k = 1, 2, 16); the line's 24k (+ pad)
is Rule A's (rev 7, owner-reviewed): the dropped 2B+16 is 48 of 432 = 11.1% at size 16 (B = 16), so it stands.

**Front-line table: empty for screen.fj** (no macro's own line is wrong by the conventions). The cross-cutting lines
with an undefined name are listed under (d3); the ones that change a formula were already rows in batches 1-3
(cross-referenced there), so no new front-line row comes from batch 6.

## Mutants (screen.fj) the current tests miss

`mutants6.log`: baseline 23 passed; both CTRLs caught (output_bits msb-first; init_screen w/h swapped). Also caught:
define_palette with no pad / the pad mod 4 / the last field's top bit dropped, set_window_title without its 0,
end_frame `<` -> `<=` at 15 / 255 / 4095, end_command ignoring used_bits / without its final `%8` / END_CMD - 1.

**MISSED** (`tests/unit/test_stl_devices.py` passes with each):

| mutant | change | why the tests miss it | an edge6 case that catches it (`mutants6_edge.log`) |
|---|---|---|---|
| `icon_header_w_h_swapped` | the icon's width and height swapped | the only icon is 1 x 1 | "set_window_icon_header 2, 3 (w != h)" |
| `icon_header_7_bits` | `width & 0x7f`, `height & 0x7f` | icon 1 x 1 | the 255 x 1 icon |
| `init_screen_width_15_bits` | `width & 0x7fff` | init widths 2..4 only (the end_frame test never inits) | end_frame w = 65534 |
| `init_screen_height_15_bits` | `height & 0x7fff` | heights 1..3 | **none of edge6's either**: add `init_screen 1, 65531, 1` + present, check `height` |
| `set_max_fps_7_bits` | `fps & 0x7f` | fps 30 | set_max_fps 255 |
| `select_palette_slot_7_bits` | `slot & 0x7f` | slot 1 | every define_palette case (slot 200) |
| `define_palette_slot_7_bits` | `slot & 0x7f` | slot 1 | the same |
| `builtin_palette_slot_7_bits` | `slot & 0x7f` | slot 3 | **none of edge6's either** (its slot-255 case loads id 4 = format 5's default): add `builtin_palette 200, 2` at format 8, check slot 200 is EGA-16 |
| `builtin_palette_id_2_bits` | `id & 3` | id 2 | builtin id 4 |
| `define_palette_index_bit_8_dropped` | first / last `& ~0x100` | formats 3..8 only | format 9 [511,511] (formats 9-16 are untested) |
| `end_command_used_bits_low_2_only` | `(used_bits&4)` | used_bits 0 and 4 only | used_bits 0..7 |

Tests to add (the smallest set): the 2 x 3 icon; set_max_fps 255; select / define / builtin at slot 200 (builtin id 4 and
a non-default id); define_palette at format 9 or 16 with first = last = 2^B - 1; init_screen 65534 x 1 and 1 x 65531;
end_frame at used_bits 1..7. Each is an edge6 POS body.

# Part 2: the cross-cutting checks (the whole stl, 402 defs)

**"Public" (the rule used):** a def none of whose name components starts with `_`. No stl comment or README calls any
namespace internal (`grep -i "internal\|private\|helper"` over the stl finds only strings.fj's header, which calls its
public macros "helpers"), so every other namespace counts, sub-namespaces (`hex.tables`, `hex.pointers`, `hex.add`,
`hex.mul`, ...) included. Private by the rule (11): the 9 `__relocatable__.table` defs, `bit._.cmp_next_eq` and
`bit._.print_str_one_char`. Public: 391.

The (a), (b) and (d2) lists are generated (`gen_lists.py` from `xcut.json`) and follow; (c), (d1) and (d3) after them.

### (a) public defs without a doc comment or without a Complexity line

| file:line | macro | gap | note |
|---|---|---|---|
| `bit/casting.fj:7` | `bit.str/1` | no complexity line | has a description: `create a bit-vector, initialized with the value of 'str', and with the` |
| `bit/memory.fj:13` | `bit.bit/0` | no doc | the no-value overload; the doc sits on the overload right above it |
| `bit/memory.fj:23` | `bit.vec/1` | no doc | the no-value overload; the doc sits on the overload right above it |
| `bit/pointers.fj:116` | `bit.pointers.advance_by_one_and_flip__ptr_wflip/2` | no complexity line | has a description: `Advances *to_flip by 1 (which takes n flips, from bit0 to bit1, bit2,.` |
| `hex/cond_jumps.fj:35` | `hex.if0/2` | no complexity line | has a description: `if hex==0 goto l0, else continue.` |
| `hex/cond_jumps.fj:40` | `hex.if1/2` | no complexity line | has a description: `if hex!=0 goto l1, else continue.` |
| `hex/cond_jumps.fj:53` | `hex.if0/3` | no complexity line | has a description: `if hex[:n]==0 goto l0, else continue.` |
| `hex/cond_jumps.fj:58` | `hex.if1/3` | no complexity line | has a description: `if hex[:n]!=0 goto l1, else continue.` |
| `hex/cond_jumps.fj:181` | `hex.cmp.cmp_eq_next/4` | no complexity line | has a description: `compares a to b; if equal just continue.` |
| `hex/math.fj:49` | `hex.add.add_constant_with_leading_zeros/4` | no doc |  |
| `hex/math.fj:52` | `hex.add.add_hex_shifted_constant/4` | no doc |  |
| `hex/math.fj:217` | `hex.sub.sub_constant_with_leading_zeros/4` | no doc |  |
| `hex/math.fj:220` | `hex.sub.sub_hex_shifted_constant/4` | no doc |  |
| `hex/math_basic.fj:135` | `hex.inc.step/2` | no doc |  |
| `hex/math_basic.fj:182` | `hex.dec.step/2` | no doc |  |
| `hex/memory.fj:13` | `hex.hex/0` | no doc | the no-value overload; the doc sits on the overload right above it |
| `hex/memory.fj:23` | `hex.vec/1` | no doc | the no-value overload; the doc sits on the overload right above it |
| `hex/pointers/pointer_arithmetics.fj:73` | `hex.pointers.ptr_index/5` | no complexity line | has a description: `dst[:w/4] = ptr + index*2w    (see hex.ptr_index n; index*2w fits sw h` |
| `hex/pointers/read_pointers.fj:211` | `hex.pointers.entry_address/6` | no complexity line | has a description: `the same, with c = size*2w and sw = the hexes idx*c needs.` |
| `hex/pointers/xor_to_pointer.fj:190` | `hex.pointers.advance_by_one_and_flip__ptr_wflip/2` | no complexity line | has a description: `Advances *to_flip by 1 (which takes n flips, from bit0 to bit1, bit2,.` |
| `hex/tables_init.fj:21` | `hex.tables.init_shared/0` | no complexity line | has a description: `Allocates the shared `ret` and `res` symbols used by every` |
| `hex/tables_init.fj:27` | `hex.tables.init_all/0` | no complexity line | has a description: `This is the inner-macro of hex.init, and it's identical to it. see hex` |
| `runlib.fj:149` | `stl.comp_if/3` | no complexity line | has a description: `if expression is 0 (compilation time), jump to l0. else jump to l1` |
| `runlib.fj:154` | `stl.comp_if0/2` | no complexity line | has a description: `if expression is 0 (compilation time), jump to l0. else continue` |
| `runlib.fj:160` | `stl.comp_if1/2` | no complexity line | has a description: `if expression is not 0 (compilation time), jump to l1. else continue` |
| `runlib.fj:169` | `stl.comp_flip_if/2` | no complexity line | has a description: `if expr != 0 (compilation time), flip the given bit.` |
| `runlib.fj:180` | `stl.skip/0` | no complexity line | has a description: `skip the next flipjump op` |
| `runlib.fj:186` | `stl.loop/0` | no complexity line | has a description: `finish (loop to self)` |

### (b) every precondition claim in the stl: is it tested?

"Uses" = direct test programs calling the macro / test programs reaching it through other macros. Every `@requires` violation is loud by construction (the init defines the labels, so a missing init is an "undefined label" assembly error); none has a test, and none needs one.

| file:line | macro | claim | uses (direct / reached) | violation (or the allowed case) tested |
|---|---|---|---|---|
| `bit/div.fj:23` | `bit.div10.cmp_sub_10/3` | for val4:val[3,2,1,0] of length 5, and Assumes val <= 19. | 0 / 494 | none |
| `bit/math.fj:10` | `bit.inc1/2` | Unsafe for dst==carry (but there is no reason in calling it that way) | 1 / 231 | none |
| `bit/math.fj:21` | `bit.inc.inc1_with_carry0_jump/3` | Unsafe for dst==carry (but there is no reason in calling it that way) | 0 / 306 | none |
| `bit/math.fj:67` | `bit.add1/3` | Unsafe for dst==carry (but there is no reason in calling it that way) | 0 / 230 | none |
| `bit/memory.fj:10` | `bit.bit/1` | you can't place it as any other standard library macro, as "running" this line is undefined behavior. | 11 / 910 | none |
| `bit/memory.fj:83` | `bit.mov/3` | note: doesn't work if dst and src overlap. works if dst==src. | 162 / 597 | the allowed dst == src: NONE; the forbidden overlap: none |
| `bit/mul.fj:27` | `bit.mul_loop/3` | @Assumes: dst and src are NOT the same address (aliasing makes this macro loop forever). | 2 / 2 | none |
| `bit/mul.fj:27` | `bit.mul_loop/3` | For squaring (dst==src) use the mul macro, which handles aliasing safely. | 2 / 2 | the claim that bit.mul squares safely: NONE (no test calls bit.mul n, x, x) |
| `bit/output.fj:76` | `bit.print_hex_uint/3` | @Assumes n can be divided by 4. | 3 / 10 | none |
| `bit/output.fj:122` | `bit.print_hex_int/3` | @Assumes n can be divided by 4. | 7 / 7 | none |
| `bit/pointers.fj:53` | `bit.ptr_jump/1` | @requires bit.pointers.ptr_init | 1 / 2 | loud (assembly error), no test |
| `bit/pointers.fj:70` | `bit.ptr_flip/1` | @requires bit.pointers.ptr_init | 4 / 5 | loud (assembly error), no test |
| `bit/pointers.fj:88` | `bit.ptr_flip_dbit/1` | ptr is a bit[:w] that holds an address, which we assume is dw-aligned. | 1 / 1 | none |
| `bit/pointers.fj:88` | `bit.ptr_flip_dbit/1` | @requires bit.pointers.ptr_init | 1 / 1 | loud (assembly error), no test |
| `bit/pointers.fj:98` | `bit.xor_to_ptr/2` | ptr is a bit[:w] that holds an address, which we assume is dw-aligned. | 1 / 1 | none |
| `bit/pointers.fj:98` | `bit.xor_to_ptr/2` | @requires bit.pointers.ptr_init | 1 / 1 | loud (assembly error), no test |
| `bit/pointers.fj:109` | `bit.ptr_wflip/2` | ptr is a bit[:w] that holds an address, which we assume is w-aligned. | 1 / 2 | none |
| `bit/pointers.fj:109` | `bit.ptr_wflip/2` | @requires bit.pointers.ptr_init | 1 / 2 | loud (assembly error), no test |
| `bit/pointers.fj:132` | `bit.ptr_wflip_2nd_word/2` | ptr is a bit[:w] that holds an address, which we assume is dw-aligned. | 0 / 2 | none |
| `bit/pointers.fj:132` | `bit.ptr_wflip_2nd_word/2` | @requires bit.pointers.ptr_init | 0 / 2 | loud (assembly error), no test |
| `bit/pointers.fj:149` | `bit.xor_from_ptr/2` | dst is a bit. ptr is a bit[:w] that holds an address, which we assume is dw-aligned. | 2 / 2 | none |
| `bit/pointers.fj:149` | `bit.xor_from_ptr/2` | @requires bit.pointers.ptr_init | 2 / 2 | loud (assembly error), no test |
| `bit/pointers.fj:157` | `bit.exact_xor_from_ptr/2` | dst is a bit-address. ptr is a bit[:w] that holds an address, which we assume is dw-aligned. | 0 / 2 | none |
| `bit/pointers.fj:157` | `bit.exact_xor_from_ptr/2` | @requires bit.pointers.ptr_init | 0 / 2 | loud (assembly error), no test |
| `bit/shifts.fj:15` | `bit.shr/3` | @Assumes: times <= n | 1 / 8 | none |
| `bit/shifts.fj:24` | `bit.shra/3` | @Assumes: times <= n | 1 / 1 | none |
| `bit/shifts.fj:40` | `bit.shl/3` | @Assumes: times <= n | 4 / 187 | none |
| `hex/cond_jumps.fj:135` | `hex.cmp/5` | @requires hex.cmp.init (or hex.init) | 1 / 503 | loud (assembly error), no test |
| `hex/cond_jumps.fj:174` | `hex.cmp/6` | @requires hex.cmp.init (or hex.init) | 422 / 502 | loud (assembly error), no test |
| `hex/cond_jumps.fj:193` | `hex.cmp.init/0` | @requires hex.tables.init_shared (or hex.init) | 0 / 639 | loud (assembly error), no test |
| `hex/cond_jumps.fj:222` | `hex.min/4` | @Assumes dst is distinct from a and b | 13 / 13 | none |
| `hex/cond_jumps.fj:222` | `hex.min/4` | @requires hex.cmp.init (or hex.init) | 13 / 13 | loud (assembly error), no test |
| `hex/cond_jumps.fj:238` | `hex.max/4` | @Assumes dst is distinct from a and b | 13 / 13 | none |
| `hex/cond_jumps.fj:238` | `hex.max/4` | @requires hex.cmp.init (or hex.init) | 13 / 13 | loud (assembly error), no test |
| `hex/cond_jumps.fj:263` | `hex.scmp/6` | @requires hex.cmp.init (or hex.init) | 12 / 12 | loud (assembly error), no test |
| `hex/div.fj:11` | `hex.div/7` | @requires hex.sub.init & hex.cmp.init (or hex.init) | 92 / 95 | loud (assembly error), no test |
| `hex/div.fj:86` | `hex.idiv/8` | @requires hex.sub.init & hex.cmp.init (or hex.init) | 2 / 3 | loud (assembly error), no test |
| `hex/div.fj:169` | `hex.fixed_div/6` | a,b,dst are signed Q-format hex[:n] with f fraction-hexes (dst may alias a/b). div0 is an address. | 1 / 1 | the allowed alias: yes (hexlib-fixed_point: x, x, y and y, x, y) |
| `hex/div.fj:169` | `hex.fixed_div/6` | @Assumes: 0 < f <= n. | 1 / 1 | none |
| `hex/div.fj:169` | `hex.fixed_div/6` | @requires hex.sub.init & hex.cmp.init (or hex.init) | 1 / 1 | loud (assembly error), no test |
| `hex/input.fj:52` | `hex.poll_key/2` | its status, and must be read, or every later poll is out of phase. Polling never waits. | 1 / 1 | yes (test_stl_devices.py::test_poll_key_negative_control: half a keycode read -> out of phase) |
| `hex/input.fj:116` | `hex.input_dec_uint_until/3` | @requires hex.init | 9 / 317 | loud (assembly error), no test |
| `hex/input.fj:141` | `hex.input_dec_int_until/3` | @requires hex.init | 1 / 29 | loud (assembly error), no test |
| `hex/input.fj:178` | `hex.input_dec_uint/3` | @requires hex.init | 309 / 309 | loud (assembly error), no test |
| `hex/input.fj:193` | `hex.input_dec_int/3` | @requires hex.init | 28 / 28 | loud (assembly error), no test |
| `hex/logics.fj:385` | `hex.or/2` | @requires hex.or.init (or hex.init) | 3 / 3 | loud (assembly error), no test |
| `hex/logics.fj:393` | `hex.or/3` | @requires hex.or.init (or hex.init) | 7 / 7 | loud (assembly error), no test |
| `hex/logics.fj:405` | `hex.or.init/0` | @requires hex.tables.init_shared (or hex.init) | 0 / 639 | loud (assembly error), no test |
| `hex/logics.fj:435` | `hex.and/2` | @requires hex.and.init (or hex.init) | 2 / 2 | loud (assembly error), no test |
| `hex/logics.fj:443` | `hex.and/3` | @requires hex.and.init (or hex.init) | 15 / 15 | loud (assembly error), no test |
| `hex/logics.fj:455` | `hex.and.init/0` | @requires hex.tables.init_shared (or hex.init) | 0 / 639 | loud (assembly error), no test |
| `hex/math.fj:12` | `hex.add/2` | @requires hex.add.init (or hex.init) | 1 / 1 | loud (assembly error), no test |
| `hex/math.fj:20` | `hex.add/3` | @requires hex.add.init (or hex.init) | 176 / 407 | loud (assembly error), no test |
| `hex/math.fj:30` | `hex.add_shifted/5` | @requires hex.add.init (or hex.init) | 3 / 149 | loud (assembly error), no test |
| `hex/math.fj:44` | `hex.add_constant/3` | @requires hex.add.init (or hex.init) | 1 / 144 | loud (assembly error), no test |
| `hex/math.fj:44` | `hex.add_constant/3` | const must be a positive constant. | 1 / 144 | NONE (const = 0 / negative: batch 3 B2, batch 5 B2) |
| `hex/math.fj:60` | `hex.add.add_hex_shifted_constant/5` | @requires hex.add.init (or hex.init) | 0 / 144 | loud (assembly error), no test |
| `hex/math.fj:74` | `hex.add.clear_carry/0` | @requires hex.add.init (or hex.init) | 1 / 429 | loud (assembly error), no test |
| `hex/math.fj:85` | `hex.add.clear_carry/2` | @requires hex.add.init (or hex.init) | 2 / 150 | loud (assembly error), no test |
| `hex/math.fj:104` | `hex.add.chain/5` | @Assumes: n >= 1. | 0 / 468 | none |
| `hex/math.fj:104` | `hex.add.chain/5` | @requires hex.add.init (or hex.init) | 0 / 468 | loud (assembly error), no test |
| `hex/math.fj:123` | `hex.add.not_carry/0` | @requires hex.add.init (or hex.init) | 1 / 2 | loud (assembly error), no test |
| `hex/math.fj:131` | `hex.add.set_carry/0` | @requires hex.add.init (or hex.init) | 1 / 1 | loud (assembly error), no test |
| `hex/math.fj:143` | `hex.add.init/0` | @requires hex.tables.init_shared (or hex.init) | 0 / 639 | loud (assembly error), no test |
| `hex/math.fj:182` | `hex.sub/2` | @requires hex.sub.init (or hex.init) | 1 / 1 | loud (assembly error), no test |
| `hex/math.fj:190` | `hex.sub/3` | @requires hex.sub.init (or hex.init) | 138 / 206 | loud (assembly error), no test |
| `hex/math.fj:200` | `hex.sub_shifted/5` | @requires hex.sub.init (or hex.init) | 2 / 43 | loud (assembly error), no test |
| `hex/math.fj:213` | `hex.sub_constant/3` | @requires hex.sub.init (or hex.init) | 0 / 41 | loud (assembly error), no test |
| `hex/math.fj:228` | `hex.sub.sub_hex_shifted_constant/5` | @requires hex.sub.init (or hex.init) | 0 / 41 | loud (assembly error), no test |
| `hex/math.fj:242` | `hex.sub.clear_carry/0` | @requires hex.sub.init (or hex.init) | 1 / 207 | loud (assembly error), no test |
| `hex/math.fj:251` | `hex.sub.clear_carry/2` | @requires hex.sub.init (or hex.init) | 2 / 240 | loud (assembly error), no test |
| `hex/math.fj:271` | `hex.sub.chain/5` | @Assumes: n >= 1. | 0 / 239 | none |
| `hex/math.fj:271` | `hex.sub.chain/5` | @requires hex.sub.init (or hex.init) | 0 / 239 | loud (assembly error), no test |
| `hex/math.fj:295` | `hex.sub.not_carry/0` | @requires hex.sub.init (or hex.init) | 1 / 240 | loud (assembly error), no test |
| `hex/math.fj:303` | `hex.sub.set_carry/0` | @requires hex.sub.init (or hex.init) | 1 / 1 | loud (assembly error), no test |
| `hex/math.fj:315` | `hex.sub.init/0` | This is where the sub "truth" tables are. must be called once if you want to use hex.sub (hex.init calls it). | 0 / 639 | none |
| `hex/math.fj:315` | `hex.sub.init/0` | @requires hex.tables.init_shared (or hex.init) | 0 / 639 | loud (assembly error), no test |
| `hex/math_basic.fj:11` | `hex.add_count_bits/3` | @Assumes: dst and src do not alias. | 1 / 115 | none |
| `hex/memory.fj:10` | `hex.hex/1` | you can't place it as any other standard library macro, as "running" this line is undefined behavior. | 6 / 598 | none |
| `hex/memory.fj:64` | `hex.mov/3` | Unsafe if dst and src overlap! but safe if they are the exact same address. | 329 / 395 | the allowed dst == src: NONE; the forbidden overlap: none |
| `hex/memory.fj:115` | `hex.swap/3` | Unsafe if dst and src overlap! but safe if they are the exact same address. | 1 / 1 | the allowed dst == src: NONE; the forbidden overlap: none |
| `hex/mul.fj:8` | `hex.add_mul/2` | @requires hex.add.init (or hex.init) | 1 / 1 | loud (assembly error), no test |
| `hex/mul.fj:23` | `hex.add_mul/4` | @requires hex.add.init (or hex.init) | 6 / 378 | loud (assembly error), no test |
| `hex/mul.fj:33` | `hex.mul10/2` | @requires hex.add.init (or hex.init) | 8 / 339 | loud (assembly error), no test |
| `hex/mul.fj:50` | `hex.mul/4` | @requires hex.add.init (or hex.init) | 110 / 111 | loud (assembly error), no test |
| `hex/mul.fj:102` | `hex.mul.chain/4` | @Assumes: n >= 1. | 0 / 378 | none |
| `hex/mul.fj:102` | `hex.mul.chain/4` | @requires hex.add.init & hex.mul.init (or hex.init) | 0 / 378 | loud (assembly error), no test |
| `hex/mul.fj:121` | `hex.mul.chained_clear_carry/1` | @Assumes: .ret holds prev_return (0 if it's clear). Like hex.tables.chained_jump, but for .ret: | 0 / 378 | none |
| `hex/mul.fj:136` | `hex.mul.chained_add_mul/3` | @Assumes: .ret holds prev_return (see chained_clear_carry). | 0 / 378 | none |
| `hex/mul.fj:151` | `hex.mul.chain_step/3` | @Assumes: the previous step's end is this macro's start (see hex.tables.chained_jump). | 0 / 378 | none |
| `hex/mul.fj:165` | `hex.mul.init/0` | @requires hex.tables.init_shared & hex.add.init (or hex.init) | 0 / 639 | loud (assembly error), no test |
| `hex/mul.fj:257` | `hex.mul_low/4` | res,a,b are hex[:n]; res must not alias a or b. | 1 / 1 | none |
| `hex/mul.fj:257` | `hex.mul_low/4` | @requires hex.add.init & hex.mul.init (or hex.init) | 1 / 1 | loud (assembly error), no test |
| `hex/mul.fj:282` | `hex.fixed_mul/5` | a,b,dst are signed Q-format hex[:n] with f fraction-hexes (dst may alias a/b). | 1 / 1 | the allowed alias: yes (hexlib-fixed_point) |
| `hex/mul.fj:282` | `hex.fixed_mul/5` | @Assumes: 0 < f <= n. | 1 / 1 | none |
| `hex/mul.fj:282` | `hex.fixed_mul/5` | @requires hex.add.init & hex.mul.init & hex.cmp.init (or hex.init) | 1 / 1 | loud (assembly error), no test |
| `hex/mul.fj:306` | `hex.fixed_mul_low/5` | n rows on b's hexes, and f rows on its sign-extension hexes (0xf, and only if b is negative). | 1 / 1 | none |
| `hex/mul.fj:306` | `hex.fixed_mul_low/5` | a,b,dst are signed Q-format hex[:n] with f fraction-hexes (dst may alias a/b). | 1 / 1 | the allowed alias: yes (hexlib-fixed_point) |
| `hex/mul.fj:306` | `hex.fixed_mul_low/5` | @Assumes: 0 < f <= n. | 1 / 1 | none |
| `hex/mul.fj:306` | `hex.fixed_mul_low/5` | @requires hex.add.init & hex.mul.init (or hex.init) | 1 / 1 | loud (assembly error), no test |
| `hex/mul.fj:331` | `hex.mul_const/4` | dst,src are hex[:n] (dst may alias src). | 1 / 2 | the allowed alias: yes (hexlib-fixed_point: n, x, x, c) |
| `hex/mul.fj:331` | `hex.mul_const/4` | @requires hex.add.init (or hex.init) | 1 / 2 | loud (assembly error), no test |
| `hex/pointers/basic_pointers.fj:20` | `hex.pointers.ptr_init/0` | NOTE: must be placed just after the startup, so that the read_ptr_byte_table will be at op | 0 / 589 | none |
| `hex/pointers/basic_pointers.fj:75` | `hex.pointers.wide_table_init/0` | it conditionally; it must begin at op exactly 2^PTR_WIDE_BITS, which is what | 0 / 589 | none |
| `hex/pointers/basic_pointers.fj:125` | `hex.pointers.set_jump_pointer/1` | @note: this is an ALIAS of set_flip_and_jump_pointers, and it must stay one. A setter that | 0 / 28 | none |
| `hex/pointers/basic_pointers.fj:137` | `hex.pointers.set_flip_pointer/1` | @note: an ALIAS of set_flip_and_jump_pointers, for the reason given at set_jump_pointer. | 0 / 35 | none |
| `hex/pointers/basic_pointers.fj:148` | `hex.pointers.advance/0` | @Assumes: the armed address is dw-aligned (an offset below 2w in to_flip, like the read dance's, is kept). | 0 / 47 | none |
| `hex/pointers/pointer_arithmetics.fj:9` | `hex.ptr_inc/1` | @requires hex.add.init (or hex.init) | 25 / 110 | loud (assembly error), no test |
| `hex/pointers/pointer_arithmetics.fj:17` | `hex.ptr_dec/1` | @requires hex.sub.init (or hex.init) | 9 / 34 | loud (assembly error), no test |
| `hex/pointers/pointer_arithmetics.fj:26` | `hex.ptr_add/2` | @requires hex.add.init (or hex.init) | 38 / 40 | loud (assembly error), no test |
| `hex/pointers/pointer_arithmetics.fj:35` | `hex.ptr_sub/2` | @requires hex.sub.init (or hex.init) | 7 / 9 | loud (assembly error), no test |
| `hex/pointers/pointer_arithmetics.fj:46` | `hex.ptr_index/3` | @requires hex.add.init (or hex.init) | 24 / 43 | loud (assembly error), no test |
| `hex/pointers/pointer_arithmetics.fj:46` | `hex.ptr_index/3` | @Assumes: w in {16, 32, 64, 128}. | 24 / 43 | none |
| `hex/pointers/pointer_arithmetics.fj:64` | `hex.ptr_index/4` | dst must not alias ptr, and must be index itself or not overlap it. | 1 / 1 | the allowed dst == index: yes (hexlib-ptr_index_n); the forbidden dst == ptr: none |
| `hex/pointers/pointer_arithmetics.fj:64` | `hex.ptr_index/4` | @requires hex.add.init (or hex.init) | 1 / 1 | loud (assembly error), no test |
| `hex/pointers/pointer_arithmetics.fj:64` | `hex.ptr_index/4` | @Assumes: w in {16, 32, 64, 128}. | 1 / 1 | none |
| `hex/pointers/pointer_arithmetics.fj:73` | `hex.pointers.ptr_index/5` | @requires hex.add.init (or hex.init) | 0 / 1 | loud (assembly error), no test |
| `hex/pointers/pointer_arithmetics.fj:82` | `hex.pointers.ptr_index_narrow/5` | @requires hex.add.init (or hex.init) | 0 / 1 | loud (assembly error), no test |
| `hex/pointers/pointer_arithmetics.fj:97` | `hex.pointers.ptr_index_wide/5` | @requires hex.add.init (or hex.init) | 0 / 1 | loud (assembly error), no test |
| `hex/pointers/pointer_arithmetics.fj:109` | `hex.pointers.shl_index/3` | @Assumes: k >= 4. | 0 / 2 | none |
| `hex/pointers/read_pointers.fj:9` | `hex.read_hex/2` | dst is a hex. ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 0 / 12 | none |
| `hex/pointers/read_pointers.fj:18` | `hex.read_byte/2` | dst is a hex[:2]. ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 26 / 97 | none |
| `hex/pointers/read_pointers.fj:46` | `hex.read_hex_and_inc/2` | dst is a hex. ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 0 / 0 | none |
| `hex/pointers/read_pointers.fj:57` | `hex.read_hex/3` | dst is a hex[:n]. ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 41 / 42 | none |
| `hex/pointers/read_pointers.fj:57` | `hex.read_hex/3` | @Assumes: n >= 1 (n < 1 is refused at assemble time), and dst does not overlap ptr. | 41 / 42 | n < 1: yes (test_stl_n_cell_ops.py::test_n_0_is_refused_at_assemble_time); the overlap: none |
| `hex/pointers/read_pointers.fj:69` | `hex.read_byte_and_inc/2` | dst is a hex[:2]. ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 44 / 53 | none |
| `hex/pointers/read_pointers.fj:80` | `hex.read_byte/3` | dst is a hex[:2n]. ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 6 / 7 | none |
| `hex/pointers/read_pointers.fj:80` | `hex.read_byte/3` | @Assumes: n >= 1 (n < 1 is refused at assemble time), and dst does not overlap ptr. | 6 / 7 | n < 1: yes (test_n_0_is_refused_at_assemble_time); the overlap: none |
| `hex/pointers/read_pointers.fj:93` | `hex.read_cell_and_inc/2` | dst is a hex[:PTR_WIDE/4]. ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 1 / 1 | none |
| `hex/pointers/read_pointers.fj:109` | `hex.read_nth_hex/3` | @requires hex.init and stl.ptr_init (or stl.startup_and_init_all). | 1 / 1 | loud (assembly error), no test |
| `hex/pointers/read_pointers.fj:120` | `hex.read_nth_byte/3` | @requires hex.init and stl.ptr_init (or stl.startup_and_init_all). | 18 / 18 | loud (assembly error), no test |
| `hex/pointers/read_pointers.fj:139` | `hex.read_back/1` | @Assumes: on every path here, no pointer operation (push / pop and stl.call / stl.return included) ran since. | 2 / 2 | none |
| `hex/pointers/read_pointers.fj:139` | `hex.read_back/1` | @Assumes: armed is dw-aligned (not the ptr+w of ptr_wflip_2nd_word, and so of stl.call / stl.return). | 2 / 2 | none |
| `hex/pointers/read_pointers.fj:159` | `hex.read_entry/5` | idx is an unsigned hex[:idx_n] (idx_n <= w/4); dst may alias idx. entry_address: see hex.pointers. | 1 / 1 | the allowed alias: yes (hexlib-read_entry: n, v, table, idx_n, v) |
| `hex/pointers/read_pointers.fj:159` | `hex.read_entry/5` | @requires hex.init & stl.ptr_init | 1 / 1 | loud (assembly error), no test |
| `hex/pointers/read_pointers.fj:174` | `hex.read_entry_byte/4` | idx is an unsigned hex[:idx_n] (idx_n <= w/4); dst may alias idx. | 1 / 1 | the allowed alias: NONE (passes edge5, batch 5) |
| `hex/pointers/read_pointers.fj:174` | `hex.read_entry_byte/4` | @requires hex.init & stl.ptr_init | 1 / 1 | loud (assembly error), no test |
| `hex/pointers/read_pointers.fj:190` | `hex.read_entry_packed/5` | idx is an unsigned hex[:idx_n] (idx_n <= w/4); dst may alias idx. | 1 / 1 | the allowed alias: NONE (passes edge5, batch 5) |
| `hex/pointers/read_pointers.fj:190` | `hex.read_entry_packed/5` | @requires hex.init & stl.ptr_init | 1 / 1 | loud (assembly error), no test |
| `hex/pointers/read_pointers.fj:207` | `hex.pointers.entry_address/5` | @requires hex.add.init (or hex.init) | 0 / 1 | loud (assembly error), no test |
| `hex/pointers/stack.fj:39` | `hex.push_ret_address/1` | Note: the pushed returned address must be popd out afterwards with pop_ret_address. | 0 / 27 | none |
| `hex/pointers/stack.fj:39` | `hex.push_ret_address/1` | return_address is a fj-op address, so we assume is dw-aligned. | 0 / 27 | none |
| `hex/pointers/stack.fj:50` | `hex.pop_ret_address/1` | Pops the given return_address from the current cell in the stack (assumes it has the value of the return_address). Decre | 0 / 27 | none |
| `hex/pointers/stack.fj:50` | `hex.pop_ret_address/1` | return_address is a fj-op address, so we assume is dw-aligned. | 0 / 27 | none |
| `hex/pointers/stack.fj:85` | `hex.push/2` | Note: The push/pop usage must be coordinated, and every push X must be untangled by a pop X (or a sp_sub (X+1)/2) | 7 / 7 | none |
| `hex/pointers/stack.fj:85` | `hex.push/2` | For example: "push 3; push 3" can't be read with a "pop 6". That's because each "push 3" takes 2 stack cells, | 7 / 7 | none |
| `hex/pointers/stack.fj:124` | `hex.pop/2` | Note: The pops assume that they were pushed as bytes to the stack (2 hexs in one stack-cell). | 7 / 7 | none |
| `hex/pointers/stack.fj:124` | `hex.pop/2` | Note: The push/pop usage must be coordinated, and every push X must be untangled by a pop X (or a sp_sub (X+1)/2) | 7 / 7 | none |
| `hex/pointers/stack.fj:124` | `hex.pop/2` | For example: "push 3; push 3" can't be read with a "pop 6". That's because each "push 3" takes 2 stack cells, | 7 / 7 | none |
| `hex/pointers/write_pointers.fj:9` | `hex.write_hex/2` | src is a hex. ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 0 / 12 | none |
| `hex/pointers/write_pointers.fj:23` | `hex.zero_ptr/1` | bits into read_byte, so the write-back must cover the same width: flipping back only the | 1 / 28 | none |
| `hex/pointers/write_pointers.fj:23` | `hex.zero_ptr/1` | ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 1 / 28 | none |
| `hex/pointers/write_pointers.fj:33` | `hex.write_byte/2` | src is a hex[:2]. ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 13 / 95 | none |
| `hex/pointers/write_pointers.fj:50` | `hex.write_cell/2` | The read-side twin is hex.read_cell, and the two must stay width-twins: a cell written | 1 / 1 | none |
| `hex/pointers/write_pointers.fj:68` | `hex.zero_cell_ptr/1` | @note: on a WIDE cell only this macro may zero; hex.zero_ptr is the NARROW one and must | 1 / 1 | none |
| `hex/pointers/write_pointers.fj:68` | `hex.zero_cell_ptr/1` | ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 1 / 1 | none |
| `hex/pointers/write_pointers.fj:87` | `hex.write_hex_and_inc/2` | src is a hex. ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 0 / 0 | none |
| `hex/pointers/write_pointers.fj:98` | `hex.write_hex/3` | src is a hex[:n]. ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 41 / 41 | none |
| `hex/pointers/write_pointers.fj:98` | `hex.write_hex/3` | @Assumes: n >= 1 (n < 1 is refused at assemble time), and src does not overlap ptr. | 41 / 41 | n < 1: yes (test_n_0_is_refused_at_assemble_time); the overlap: none |
| `hex/pointers/write_pointers.fj:109` | `hex.write_byte_and_inc/2` | src is a hex[:2]. ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 39 / 73 | none |
| `hex/pointers/write_pointers.fj:120` | `hex.write_byte/3` | src is a hex[:2n]. ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 5 / 5 | none |
| `hex/pointers/write_pointers.fj:120` | `hex.write_byte/3` | @Assumes: n >= 1 (n < 1 is refused at assemble time), and src does not overlap ptr. | 5 / 5 | n < 1: yes (test_n_0_is_refused_at_assemble_time); the overlap: none |
| `hex/pointers/write_pointers.fj:132` | `hex.write_cell_and_inc/2` | src is a hex[:PTR_WIDE/4]. ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 1 / 1 | none |
| `hex/pointers/write_pointers.fj:148` | `hex.write_nth_hex/3` | @requires hex.init and stl.ptr_init (or stl.startup_and_init_all). | 1 / 1 | loud (assembly error), no test |
| `hex/pointers/write_pointers.fj:159` | `hex.write_nth_byte/3` | @requires hex.init and stl.ptr_init (or stl.startup_and_init_all). | 11 / 11 | loud (assembly error), no test |
| `hex/pointers/write_pointers.fj:175` | `hex.write_back/1` | The same armed address, and @Assumes, as hex.read_back. | 1 / 1 | none |
| `hex/pointers/write_pointers.fj:215` | `hex.pointers.write_cell/2` | @Assumes: .ret_after_read_byte holds to_flip (see write_cells). | 0 / 44 | none |
| `hex/pointers/xor_from_pointer.fj:6` | `hex.xor_hex_from_ptr/2` | dst is a hex. ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 4 / 15 | none |
| `hex/pointers/xor_from_pointer.fj:16` | `hex.xor_byte_from_ptr/2` | dst is a hex[2:]. ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 0 / 97 | none |
| `hex/pointers/xor_from_pointer.fj:64` | `hex.pointers.read_cell_step/2` | @Assumes: the previous dance's landing label is this macro's start (see hex.tables.chained_jump). | 0 / 46 | none |
| `hex/pointers/xor_from_pointer.fj:77` | `hex.pointers.read_cell_chained/1` | @Assumes: to_flip+w holds prev_return (0 if it's clear). | 0 / 46 | none |
| `hex/pointers/xor_from_pointer.fj:92` | `hex.pointers.read_byte_from_inners_ptrs/0` | ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 0 / 118 | none |
| `hex/pointers/xor_from_pointer.fj:115` | `hex.pointers.read_cell_from_inners_ptrs/2` | ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 0 / 118 | none |
| `hex/pointers/xor_to_pointer.fj:25` | `hex.ptr_flip_dbit/1` | ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 2 / 2 | none |
| `hex/pointers/xor_to_pointer.fj:36` | `hex.xor_hex_to_ptr/2` | ptr is a hex[:w/4] that holds an address, which we assume is an hex-variable, which is dw-aligned. | 2 / 2 | none |
| `hex/pointers/xor_to_pointer.fj:45` | `hex.xor_byte_to_ptr/2` | ptr is a hex[:w/4] that holds an address, which we assume is an hex-variable, which is dw-aligned. | 1 / 1 | none |
| `hex/pointers/xor_to_pointer.fj:56` | `hex.xor_hex_to_ptr/3` | ptr is a hex[:w/4] that holds an address, which we assume is an hex-variable, which is dw-aligned. | 4 / 4 | none |
| `hex/pointers/xor_to_pointer.fj:56` | `hex.xor_hex_to_ptr/3` | @Assumes: n >= 1 (n < 1 is refused at assemble time), and hex does not overlap ptr. | 4 / 4 | n < 1: yes (test_n_0_is_refused_at_assemble_time); the overlap: none |
| `hex/pointers/xor_to_pointer.fj:69` | `hex.xor_byte_to_ptr/3` | ptr is a hex[:w/4] that holds an address, which we assume is an hex-variable, which is dw-aligned. | 4 / 4 | none |
| `hex/pointers/xor_to_pointer.fj:69` | `hex.xor_byte_to_ptr/3` | @Assumes: n >= 1 (n < 1 is refused at assemble time), and hex does not overlap ptr. | 4 / 4 | n < 1: yes (test_n_0_is_refused_at_assemble_time); the overlap: none |
| `hex/pointers/xor_to_pointer.fj:90` | `hex.pointers.xor_hex_to_ptr_and_inc/2` | ptr is a hex[:w/4] that holds an address, which we assume is an hex-variable, which is dw-aligned. | 0 / 0 | none |
| `hex/pointers/xor_to_pointer.fj:100` | `hex.pointers.xor_byte_to_ptr_and_inc/2` | ptr is a hex[:w/4] that holds an address, which we assume is an hex-variable, which is dw-aligned. | 0 / 0 | none |
| `hex/pointers/xor_to_pointer.fj:112` | `hex.pointers.xor_hex_to_flip_ptr/1` | It assumes that the value in the memory-word to_flip is a dw-aligned address to an hex-variable. | 0 / 17 | none |
| `hex/pointers/xor_to_pointer.fj:122` | `hex.pointers.xor_byte_to_flip_ptr/1` | It assumes that the value in the memory-word to_flip is a dw-aligned address to an hex-variable. | 0 / 99 | none |
| `hex/pointers/xor_to_pointer.fj:135` | `hex.pointers.xor_cell_to_flip_ptr/1` | PTR_CELL_BITS bits, so anything that clears or rewrites a cell must cover all of them. | 0 / 1 | none |
| `hex/pointers/xor_to_pointer.fj:147` | `hex.pointers.xor_hex_to_flip_ptr/2` | It assumes that the value in the memory-word to_flip is a dw-aligned address to an hex-variable. | 0 / 152 | none |
| `hex/pointers/xor_to_pointer.fj:147` | `hex.pointers.xor_hex_to_flip_ptr/2` | bit_shift is a constant that's assumed to be divisible by 4. | 0 / 152 | none |
| `hex/pointers/xor_to_pointer.fj:147` | `hex.pointers.xor_hex_to_flip_ptr/2` | @Assumes: bit_shift is divisible by 4. | 0 / 152 | none |
| `hex/pointers/xor_to_pointer.fj:183` | `hex.ptr_wflip/2` | ptr is a hex[:w/4] that holds an address, which we assume is w-aligned. | 3 / 28 | none |
| `hex/pointers/xor_to_pointer.fj:206` | `hex.ptr_wflip_2nd_word/2` | ptr is a hex[:w/4] that holds an address, which we assume is dw-aligned. | 0 / 27 | none |
| `hex/shifts.fj:34` | `hex.shl_hex/3` | @Assumes: times <= n | 10 / 200 | none |
| `hex/shifts.fj:53` | `hex.shr_hex/3` | @Assumes: times <= n | 10 / 121 | none |
| `hex/strings.fj:9` | `hex.input_ptr_line/2` | @requires hex.init and stl.ptr_init (or stl.startup_and_init_all). | 33 / 33 | loud (assembly error), no test |
| `hex/strings.fj:33` | `hex.print_ptr_text/2` | @requires hex.init and stl.ptr_init (or stl.startup_and_init_all). | 9 / 9 | loud (assembly error), no test |
| `hex/strings.fj:57` | `hex.print_ptr_line/2` | @requires hex.init and stl.ptr_init (or stl.startup_and_init_all). | 1 / 1 | loud (assembly error), no test |
| `hex/strings.fj:89` | `hex.fill_bytes/3` | @requires hex.init and stl.ptr_init (or stl.startup_and_init_all). | 2 / 2 | loud (assembly error), no test |
| `hex/strings.fj:111` | `hex.copy_bytes/3` | @Assumes: the buffers do not overlap. | 2 / 2 | none |
| `hex/strings.fj:111` | `hex.copy_bytes/3` | @requires hex.init and stl.ptr_init (or stl.startup_and_init_all). | 2 / 2 | loud (assembly error), no test |
| `hex/tables_init.fj:46` | `hex.tables.clean_table_entry__table/3` | @Assumes: n must be a power of 2, and it must be (1<<n)-padded. | 0 / 641 | none |
| `hex/tables_init.fj:60` | `hex.tables.clean_table_entry__table/1` | @requires hex.tables.init_shared (or hex.init) | 0 / 639 | loud (assembly error), no test |
| `hex/tables_init.fj:75` | `hex.tables.jump_to_table_entry/3` | The macro assumes that jumper_to_table is a fj-op that jumps to a 256-padded table. | 0 / 22 | none |
| `hex/tables_init.fj:75` | `hex.tables.jump_to_table_entry/3` | @requires hex.tables.init_shared (or hex.init) | 0 / 22 | loud (assembly error), no test |
| `hex/tables_init.fj:91` | `hex.tables.jump_to_table_entries/4` | @requires hex.tables.init_shared (or hex.init) | 0 / 17 | loud (assembly error), no test |
| `hex/tables_init.fj:106` | `hex.tables.chain/4` | @Assumes: n >= 2. | 0 / 17 | none |
| `hex/tables_init.fj:106` | `hex.tables.chain/4` | @requires hex.tables.init_shared (or hex.init) | 0 / 17 | loud (assembly error), no test |
| `hex/tables_init.fj:125` | `hex.tables.chained_jump/2` | @Assumes: .ret holds prev_return (0 if it's clear). From a chain's first chained_jump until the | 0 / 525 | none |
| `hex/tables_init.fj:125` | `hex.tables.chained_jump/2` | @requires hex.tables.init_shared (or hex.init) | 0 / 525 | loud (assembly error), no test |
| `hex/tables_init.fj:139` | `hex.tables.chained_jump_to_table_entry/4` | @Assumes: .ret holds prev_return (see chained_jump). | 0 / 525 | none |
| `hex/tables_init.fj:139` | `hex.tables.chained_jump_to_table_entry/4` | @requires hex.tables.init_shared (or hex.init) | 0 / 525 | loud (assembly error), no test |
| `hex/tables_init.fj:153` | `hex.tables.chain_step/4` | @Assumes: the previous step's end is this macro's start (see chained_jump). | 0 / 525 | none |
| `hex/tables_init.fj:153` | `hex.tables.chain_step/4` | @requires hex.tables.init_shared (or hex.init) | 0 / 525 | loud (assembly error), no test |
| `ptrlib.fj:7` | `stl.ptr_init/0` | NOTE: must be placed just after the startup, so that the read_ptr_byte_table will be in address 256. | 0 / 589 | none |
| `ptrlib.fj:35` | `stl.call/1` | @requires the stack_init. | 26 / 26 | loud (assembly error), no test |
| `ptrlib.fj:35` | `stl.call/1` | @Assumes: stack has room (caller-side responsibility). | 26 / 26 | none |
| `ptrlib.fj:52` | `stl.call/2` | @requires the stack_init. | 2 / 2 | loud (assembly error), no test |
| `ptrlib.fj:52` | `stl.call/2` | @Assumes: stack has room (caller-side responsibility). | 2 / 2 | none |
| `ptrlib.fj:70` | `stl.return/0` | @requires the stack_init. | 27 / 27 | loud (assembly error), no test |
| `ptrlib.fj:70` | `stl.return/0` | @Assumes: matched by a prior stl.call (stack non-empty). | 27 / 27 | NONE - and the violation is batch 5's B1 (the handler is unreachable) |
| `ptrlib.fj:80` | `stl.get_sp/1` | (Unsafe if dst overlaps with hex.pointers.sp). | 2 / 2 | none |
| `ptrlib.fj:80` | `stl.get_sp/1` | @requires the stack_init. | 2 / 2 | loud (assembly error), no test |
| `ptrlib.fj:103` | `stl.fret/1` | @Assumes: ret_reg contains a valid return address from a prior stl.fcall. | 25 / 517 | none |
| `screen.fj:79` | `screen.set_window_icon_header/2` | The width*height colours (B bits each, through the palette selected now) must follow it, then zero bits to | 1 / 1 | none |

Claims on macros NO test reaches: `hex.read_hex_and_inc/2` (hex/pointers/read_pointers.fj:46): "dst is a hex. ptr is a hex[:w/4] that holds an address, whic"; `hex.write_hex_and_inc/2` (hex/pointers/write_pointers.fj:87): "src is a hex. ptr is a hex[:w/4] that holds an address, whic"; `hex.pointers.xor_hex_to_ptr_and_inc/2` (hex/pointers/xor_to_pointer.fj:90): "ptr is a hex[:w/4] that holds an address, which we assume is"; `hex.pointers.xor_byte_to_ptr_and_inc/2` (hex/pointers/xor_to_pointer.fj:100): "ptr is a hex[:w/4] that holds an address, which we assume is".

### (d2) @requires lines against the tables each macro uses (transitively)

"needs" = the inits whose exported labels the body (or a callee, transitively) references, minus what the macro itself provides; a stated init brings what it provides and what it needs. `hex.pointers.ptr_init` = `stl.ptr_init`; `hex.pointers.wide_table_init` = stl.ptr_init with PTR_WIDE_BITS > 0; `hex.pointers.stack_init` = `stl.stack_init`.

| file | kind | needs | says | macros (line) |
|---|---|---|---|---|
| `bit/pointers.fj` | MISSING | bit.pointers.ptr_init | - | `bit.pointers.set_jump_pointer/1` (:29), `bit.pointers.set_flip_pointer/1` (:39), `bit.pointers.advance_by_one_and_flip__ptr_wflip/2` (:116) |
| `hex/cond_jumps.fj` | MISSING | hex.cmp.init, hex.tables.init_shared | - | `hex.cmp.cmp_eq_next/4` (:181) |
| `hex/div.fj` | INCOMPLETE | hex.add.init | @requires hex.sub.init & hex.cmp.init (or hex.init) | `hex.idiv/8` (:86), `hex.fixed_div/6` (:169) |
| `hex/math.fj` | MISSING | hex.add.init, hex.tables.init_shared | - | `hex.add.add_constant_with_leading_zeros/4` (:49), `hex.add.add_hex_shifted_constant/4` (:52) |
| `hex/math.fj` | MISSING | hex.sub.init, hex.tables.init_shared | - | `hex.sub.sub_constant_with_leading_zeros/4` (:217), `hex.sub.sub_hex_shifted_constant/4` (:220) |
| `hex/mul.fj` | INCOMPLETE | hex.cmp.init, hex.mul.init | @requires hex.add.init (or hex.init) | `hex.mul/4` (:50) |
| `hex/mul.fj` | INCOMPLETE | hex.mul.init | @requires hex.add.init (or hex.init) | `hex.add_mul/2` (:8), `hex.add_mul/4` (:23), `hex.mul10/2` (:33) |
| `hex/mul.fj` | MISSING | hex.add.init, hex.mul.init | - | `hex.mul.chained_add_mul/3` (:136) |
| `hex/mul.fj` | MISSING | hex.add.init, hex.mul.init, hex.tables.init_shared | - | `hex.mul.clear_carry/0` (:89), `hex.mul.chained_clear_carry/1` (:121), `hex.mul.chain_step/3` (:151), `hex.mul_low.row/5` (:266) |
| `hex/mul.fj` | MISSING | hex.add.init, hex.tables.init_shared | - | `hex.mul_const.step/5` (:346) |
| `hex/pointers/basic_pointers.fj` | MISSING | hex.pointers.ptr_init | - | `hex.pointers.wide_table_init/0` (:75), `hex.pointers.set_flip_and_jump_pointers/1` (:109), `hex.pointers.set_jump_pointer/1` (:125), `hex.pointers.set_flip_pointer/1` (:137), `hex.pointers.advance/0` (:148), `hex.pointers.advance_bit/2` (:156), `hex.ptr_jump/1` (:197) |
| `hex/pointers/read_pointers.fj` | MISSING | hex.add.init, hex.pointers.ptr_init, hex.pointers.wide_table_init, hex.tables.init_shared | - | `hex.read_cell_and_inc/2` (:93) |
| `hex/pointers/read_pointers.fj` | MISSING | hex.add.init, hex.pointers.ptr_init, hex.tables.init_shared | - | `hex.read_hex_and_inc/2` (:46), `hex.read_byte_and_inc/2` (:69) |
| `hex/pointers/read_pointers.fj` | MISSING | hex.add.init, hex.tables.init_shared | - | `hex.pointers.entry_address/6` (:211) |
| `hex/pointers/read_pointers.fj` | MISSING | hex.pointers.ptr_init | - | `hex.read_hex/2` (:9), `hex.read_byte/2` (:18), `hex.read_hex/3` (:57), `hex.read_byte/3` (:80), `hex.read_back/1` (:139) |
| `hex/pointers/read_pointers.fj` | MISSING | hex.pointers.ptr_init, hex.pointers.wide_table_init | - | `hex.read_cell/2` (:29) |
| `hex/pointers/stack.fj` | MISSING | hex.add.init, hex.pointers.ptr_init, hex.pointers.stack_init, hex.tables.init_shared | - | `hex.push_ret_address/1` (:39), `hex.push_hex/1` (:59), `hex.push_byte/1` (:69), `hex.push/2` (:85) |
| `hex/pointers/stack.fj` | MISSING | hex.add.init, hex.pointers.stack_init, hex.tables.init_shared | - | `hex.sp_inc/0` (:8), `hex.sp_add/1` (:22) |
| `hex/pointers/stack.fj` | MISSING | hex.pointers.ptr_init, hex.pointers.stack_init, hex.sub.init, hex.tables.init_shared | - | `hex.pop_ret_address/1` (:50), `hex.pop_hex/1` (:95), `hex.pop_byte/1` (:105), `hex.pop/2` (:124) |
| `hex/pointers/stack.fj` | MISSING | hex.pointers.stack_init, hex.sub.init, hex.tables.init_shared | - | `hex.sp_dec/0` (:15), `hex.sp_sub/1` (:29) |
| `hex/pointers/write_pointers.fj` | MISSING | hex.add.init, hex.pointers.ptr_init, hex.pointers.wide_table_init, hex.tables.init_shared | - | `hex.write_cell_and_inc/2` (:132) |
| `hex/pointers/write_pointers.fj` | MISSING | hex.add.init, hex.pointers.ptr_init, hex.tables.init_shared | - | `hex.write_hex_and_inc/2` (:87), `hex.write_byte_and_inc/2` (:109) |
| `hex/pointers/write_pointers.fj` | MISSING | hex.pointers.ptr_init | - | `hex.write_hex/2` (:9), `hex.zero_ptr/1` (:23), `hex.write_byte/2` (:33), `hex.write_hex/3` (:98), `hex.write_byte/3` (:120), `hex.write_back/1` (:175), `hex.pointers.write_cells/3` (:196), `hex.pointers.advance_and_write_cell/2` (:206), `hex.pointers.write_cell/2` (:215) |
| `hex/pointers/write_pointers.fj` | MISSING | hex.pointers.ptr_init, hex.pointers.wide_table_init | - | `hex.write_cell/2` (:50), `hex.zero_cell_ptr/1` (:68) |
| `hex/pointers/xor_from_pointer.fj` | MISSING | hex.pointers.ptr_init | - | `hex.xor_hex_from_ptr/2` (:6), `hex.xor_byte_from_ptr/2` (:16), `hex.pointers.xor_cells_from_inners_ptrs/3` (:47), `hex.pointers.read_cell_step/2` (:64), `hex.pointers.read_cell_chained/1` (:77), `hex.pointers.read_byte_from_inners_ptrs/0` (:92), `hex.pointers.read_cell_from_inners_ptrs/2` (:115) |
| `hex/pointers/xor_from_pointer.fj` | MISSING | hex.pointers.ptr_init, hex.pointers.wide_table_init | - | `hex.xor_cell_from_ptr/2` (:30), `hex.pointers.read_wide_from_inners_ptrs/0` (:100) |
| `hex/pointers/xor_to_pointer.fj` | MISSING | hex.add.init, hex.pointers.ptr_init, hex.tables.init_shared | - | `hex.pointers.xor_hex_to_ptr_and_inc/2` (:90), `hex.pointers.xor_byte_to_ptr_and_inc/2` (:100) |
| `hex/pointers/xor_to_pointer.fj` | MISSING | hex.pointers.ptr_init | - | `hex.ptr_flip/1` (:7), `hex.ptr_flip_dbit/1` (:25), `hex.xor_hex_to_ptr/2` (:36), `hex.xor_byte_to_ptr/2` (:45), `hex.xor_hex_to_ptr/3` (:56), `hex.xor_byte_to_ptr/3` (:69), `hex.pointers.advance_and_xor_to_flip_ptr/2` (:80), `hex.ptr_wflip/2` (:183), `hex.pointers.advance_by_one_and_flip__ptr_wflip/2` (:190), `hex.ptr_wflip_2nd_word/2` (:206) |
| `ptrlib.fj` | INCOMPLETE | hex.add.init, hex.pointers.ptr_init, hex.sub.init, hex.tables.init_shared | @requires the stack_init. | `stl.call/1` (:35), `stl.call/2` (:52) |
| `ptrlib.fj` | INCOMPLETE | hex.pointers.ptr_init | @requires the stack_init. | `stl.return/0` (:70) |

### (c) The READMEs against the defs (`readmes.py`, `readmes.txt`)

The three READMEs give names, not arities, except three overloads, all right: bit `input` (1 byte / n bytes) =
bit.input/1, /2; hex `input` (1 hex / n hexes) = hex.input/1, /2; `ptr_index` (full-width / n-hex) = hex.ptr_index/3,
/4. Every other listed name exists in its file (`readmes.txt` lists every overload's arities).

**Listed but not a macro of that name (fix the spelling):**

- `hex/README.md`, the stack.fj row: "`push_byte`/`hex`/`ret_address`" reads as `hex` (that is hex.hex, memory.fj) and
  `ret_address`. Write `push_byte` / `push_hex` / `push_ret_address`.
- `stl/README.md`, the bit/pointers.fj bullet: "flip, jump, xor_to, xor_from, inc/dec": the macros are `ptr_flip`,
  `ptr_jump`, `xor_to_ptr`, `xor_from_ptr`, `ptr_inc` / `ptr_dec`.
- `stl/README.md`, the bit/output.fj bullet: "output bits, bytes": there is no `bytes` (bit.output, bit.print).
- `bit/README.md`, the cond_jumps row lists `cmp_next_eq`, which is private (`bit._.cmp_next_eq`).
- (prose, fine: stl/README's tables_init "or,and, add,sub, cmp, mul" are the tables, not macros.)

**Public macros no README row of their file names** (the union of the stl/ and the bit/ / hex/ README rows):

- top namespace:
  - `bit/logics.fj`: `bit.xor_zero`/2, /3
  - `bit/pointers.fj`: `bit.ptr_wflip_2nd_word`, `bit.exact_xor_from_ptr`, `bit.ptr_inc`, `bit.ptr_dec`
  - `hex/cond_jumps.fj`: `hex.scmp`
  - `hex/logics.fj`: `hex.xor_zero`/2, /3, `hex.double_xor`, and the 11 sparse forms (`sparse_xor`/3, /4,
    `sparse_exact_xor`, `sparse_double_exact_xor`, `sparse_double_xor`, `sparse_xor_zero`/3, /4, `sparse_zero`/2, /3,
    `sparse_mov`/3, /4); `double_exact_xor`, `triple_exact_xor`, `quadrupled_exact_xor` only as "the exact_xor family
    (1/2/3/4 destination groups)" - name them
  - `hex/pointers/xor_to_pointer.fj`: `hex.ptr_flip_dbit`
  - `hex/shifts.fj`: `hex.shl_bit`, `hex.shr_bit`
  - `runlib.fj` (19 defs), `ptrlib.fj` (8), `screen.fj` (13): no list at all. Their stl/README sections are prose;
    screen's names init_screen, draw_collines, end_frame, present and "palettes, window title/icon/fps", but not
    `output_bits`, `draw_raw`, `end_command`. runlib's names none (startup*, fj, wflip_macro, comp_if*, skip, loop,
    output_bit / output_char / output); ptrlib's names none (ptr_init, stack_init, call/1, /2, return, get_sp, fcall,
    fret).
- sub-namespaces (README prose covers some as "machinery" / "helpers"; name them or call them internal):
  - `bit/div.fj`: `bit.div10.cmp_sub_10`; `bit/math.fj`: `bit.inc.inc1_with_carry0_jump`; `bit/output.fj`:
    `bit.print_hex_uint.print_digit`, `bit.print_dec_uint.print_char`; `bit/pointers.fj`: `bit.pointers.set_jump_pointer`,
    `set_flip_pointer`, `advance_by_one_and_flip__ptr_wflip`
  - `hex/logics.fj`: `hex.or.init`, `hex.and.init` (cond_jumps' `cmp.init` IS listed)
  - `hex/math.fj`: `hex.add.add_constant_with_leading_zeros`, `hex.add.init`, `hex.sub.sub_constant_with_leading_zeros`,
    `hex.sub.sub_hex_shifted_constant`/4, /5, `hex.sub.init` (the add twin `add_hex_shifted_constant` is listed)
  - `hex/mul.fj`: `hex.mul.clear_carry`, `chain`, `chained_clear_carry`, `chained_add_mul`, `chain_step`, `init`,
    `hex.mul_low.row`, `hex.mul_const.step`
  - `hex/pointers/basic_pointers.fj`: `hex.pointers.wide_table_init`, `advance`, `advance_bit`;
    `pointer_arithmetics.fj`: `ptr_index_narrow`, `ptr_index_wide`, `shl_index`; `read_pointers.fj`: `entry_address`/5,
    /6; `write_pointers.fj`: `write_cells`, `advance_and_write_cell`; `xor_from_pointer.fj`: `xor_cells_from_inners_ptrs`,
    `read_cell_step`, `read_cell_chained`; `xor_to_pointer.fj`: `advance_and_xor_to_flip_ptr`, `xor_hex_to_ptr_and_inc`,
    `xor_byte_to_ptr_and_inc`, `advance_by_one_and_flip__ptr_wflip`
  - `hex/tables_init.fj`: `hex.tables.init_shared`, `init_all`, `clean_table_entry__table`/3, /1, `jump_to_table_entry`,
    `jump_to_table_entries`, `chain`, `chained_jump`, `chained_jump_to_table_entry`, `chain_step` (the README says
    "the `tables.*` machinery")

### (d1) Parameter naming (n, dst, src, res)

`n` first then `dst` then `src` holds everywhere it applies: no def puts `src` before `dst`; `n` is not first only in
the sparse forms (`PAD` first, by design). The inconsistencies:

1. **`res` vs `dst` for the output:** the mul family says `res` - `hex.add_mul`/2 (mul.fj:8), /4 (:23), `hex.mul` (:50),
   `hex.mul_low` (:257), and the internal `hex.mul.chain`, `chained_add_mul`, `chain_step`, `mul_low.row`;
   `bit.div10.cmp_sub_10` (div.fj:23). The same file's `fixed_mul`, `fixed_mul_low`, `mul_const` and the rest of the stl
   say `dst`. Rename `res` -> `dst` (a parameter rename is free; the ABI is positional).
2. **Two spellings of the same sizes in one file:** `add_shifted` / `sub_shifted` take `dst_n, src_n` (math.fj:30,
   :200); `add_hex_shifted_constant` / `sub_hex_shifted_constant` take `n_dst, n_const` (math.fj:60, :228). Pick one
   (`dst_n`, `const_n`).
3. **`nb` means two things:** `hex.div` / `idiv` `nb` = b's hexes (div.fj:11, :86); `hex.read_entry_packed nb` = bytes
   (read_pointers.fj:190), where `hex.read_byte n` says plain `n` for bytes.
4. **The single (in-place) operand has three names:** `x` (bit.inc / dec / neg / zero / one / shl / shr / shra / rol /
   ror, hex.neg / not / zero / abs / mul10), `hex` (hex.inc / dec), `dst` (hex.shl_hex / shr_hex / shl_bit / shr_bit,
   bit.not). The same shift is `bit.shl n, times, x` and `hex.shl_hex n, times, dst`.
5. **A parameter named `hex`** in 48 defs of `ns hex` (e.g. `hex.inc n, hex`): legal, and confusing next to `hex.`
   calls.
6. **`PAD`** (logics.fj:488-655, the sparse forms) is the stl's only upper-case parameter; say in their docs "PAD, then
   the usual n, dst, src".
7. strings.fj: `len` (input_ptr_line, print_ptr_text, print_ptr_line) and `count` (fill_bytes, copy_bytes) for the same
   role (a run-time hex[:w/4] length).

### (d3) Complexity lines against the conventions' style (`cxstyle.py`, `cxstyle.txt`: 610 lines checked)

**Hard violations** (no "~", no "exact", a `Complexity:` with its colon, no bound, no approximation word):

| file:line (the def) | macro | rule | the line |
|---|---|---|---|
| `hex/input.fj:116` | `hex.input_dec_uint_until/3` | "~" (T and S) | `~ nd(7@+53)`, `~ n(9@+161)` |
| `hex/input.fj:141` | `hex.input_dec_int_until/3` | "~" (T and S) | `~ nd(7@+53)`, `~ n(10.5@+178)` |
| `hex/input.fj:178` | `hex.input_dec_uint/3` | "~" (T and S) | `~ nd(7@+53)`, `~ n(9@+161)` |
| `hex/input.fj:193` | `hex.input_dec_int/3` | "~" (T and S) | `~ nd(7@+53)`, `~ n(10.5@+178)` |
| `hex/math_basic.fj:192` | `hex.neg/2` | "~", k*n form | `~@+4n` (batch 3 F3: `4n + 1.067@`) |
| `ptrlib.fj:35` | `stl.call/1` | "~", "exact", "<" | `~2.5w@ (exact: w(2@+11) + 20@+78)`, S `<3w@ (exact: ...)` |
| `ptrlib.fj:52` | `stl.call/2` | "exact", "<" | `<3w@ (exact: w(2@+11) + 30@+100)`, S `<3w@ (exact: ...)` |
| `runlib.fj:94` | `stl.startup_and_init_all/0` | "~" | `~7000  (7010 for w=64, 6890 for w=16)` |
| `hex/math_basic.fj:130`, `:177` | `hex.inc/2`, `hex.dec/2` | "exact", "on average" | `1.067@     // It's on average. To be exact: 16/15 * @.` |
| `bit/output.fj:150`, `:229` | `bit.print_dec_uint/2`, `bit.print_dec_int/2` | two formulas, "actually" | `n^2(2@+4)  // actually: nd(7@+12)` |
| `bit/pointers.fj:109` | `bit.ptr_wflip/2` | no ":", "actually" | `Complexity 3w@  (actually a bit smaller, 3w@+3w)` |
| `bit/casting.fj:21`, `:31` | `bit.bin2ascii/2`, `bit.dec2ascii/2` | no ":" | `Complexity 9@-7`, `Complexity 12@-10` |
| `bit/output.fj:4`, `:25`, `:33` | `bit.output/1`, `bit.print/2`, `bit.print_str/2` | no ":" | `Complexity @+2`, `n(8@+16)`, `min(n, len+1)*(16@+32)` |
| `bit/pointers.fj:88`, `:98`, `:132`, `:149`, `:157` | `bit.ptr_flip_dbit`, `xor_to_ptr`, `ptr_wflip_2nd_word`, `xor_from_ptr`, `exact_xor_from_ptr` | no ":" | `Complexity 2w@ + 2@`, ... `8w@` |
| `bit/memory.fj:10`, `:20`; `hex/memory.fj:10`, `:20` | `bit.bit/1`, `bit.vec/2`, `hex.hex/1`, `hex.vec/2` | "Size Complexity" (elsewhere "Space") | `Size Complexity: 1`, `n` |
| `hex/pointers/basic_pointers.fj:148` | `hex.pointers.advance/0` | "on average" in the note | `2@+6  (two advance_bits on average ...)` |
| `hex/pointers/xor_from_pointer.fj:77` | `hex.pointers.read_cell_chained/1` | "on average" in the note | `18  (... 5.7 and 2.9 on average ...)`, S `9` |

(The "~" on the four input_dec lines survives though the front-line doc's round 4 lists them without it; batch 5's
proposed F3 / F4 / F5 lines, "T: ~w@ (exact: ...)", repeat the style these rules reject: write them as
`w(@+10) + 0.5@^2 + 20.5@ + 81`.)

**Soft (an owner's call): a size term written k*n / k*w instead of n(k) / w(k):** bit/math.fj:47 `bit.dec` `2n + 5@+12`;
bit/pointers.fj:13 `ptr_init` `2w+2`, :29 `set_jump_pointer` `2n@`, :39 `set_flip_pointer` `2w@`, :53 `ptr_jump`
`2w@ + 2`, :70 `ptr_flip` `2w@ + @`, :88, :98, :109, :132, :149, :157 (`2w@ ...`, `3w@`, `8w@`), :187 `ptr_dec` `2w + 5@+12`;
hex/logics.fj:374 `hex.not` `4n`; hex/math_basic.fj:192 `hex.neg` `@+4n`, :201 `hex.abs` `2@+4n`; hex/memory.fj:79
`hex.xor_by` `4n (avg. 2n: #on-bits)`; basic_pointers.fj:20 `ptr_init` S `0.5w + ...`; ptrlib.fj:7 `stl.ptr_init`
`2.5w+263`, :35 / :52 `stl.call`; runlib.fj:76, :85 `startup_and_init_pointers` `2.5w+265`, :102, :111
`startup_and_init_all` `6725 + 2.5w+@ + n`.

**A name in the formula that is not a parameter nor defined in the doc** (`cxnames.py`, `cxnames.txt`):

| file:line (the Complexity line) | macro | name | fix | already a row? |
|---|---|---|---|---|
| `bit/pointers.fj:25` | `bit.pointers.set_jump_pointer` | `2n@` (no n) | `2w@` | batch 2 F19 |
| `ptrlib.fj:75-76` | `stl.get_sp` | `n(2@)`, `n(2@+24)` (no n) | `w(0.5@)`, `w(0.5@+6)` | batch 1 |
| `runlib.fj:98`, `:107` | `stl.startup_and_init_all`/1, /2 | `+ n` for `stack_bit_size` | `+ stack_bit_size` (batch 1's row also adds the stack's 330) | batch 1 |
| `hex/math.fj:38-39`, `:208-209` | `hex.add_constant`/3, `hex.sub_constant`/3 | `n_const`, `dst_n`, `hex_shift` (params: n, dst, const) | define them (batch 3) | batch 3 MINOR 5 |
| `hex/math.fj:56`, `:224` | `hex.add.add_hex_shifted_constant`/5, `hex.sub.sub_hex_shifted_constant`/5 | `dst_n` for the parameter `n_dst` | `n_dst` (or rename the parameter, d1 #2) | new (a rename) |
| `bit/output.fj:31` | `bit.print_str` | `len` | "len = the string's length up to its '\0'" | new (doc) |
| `runlib.fj:207`; `screen.fj:65` | `stl.output`, `screen.set_window_title` | `string_length` | "((#str)+7)/8 bytes" | new (doc) |
| `bit/output.fj:196` | `bit.print_dec_uint.div10_step` | `n(7@+12)`: print_dec_uint's n (its doc says so) | none needed | - |

None of the new ones changes a formula's value, so none is a front-line row.

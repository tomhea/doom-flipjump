# -D OVERRIDES a declaration; it does not make one. So every program here declares the constant
# it is about to have overridden -- a program that does not is the subject of
# test_cli_define_of_an_undeclared_constant_is_refused.
DEFINE_PROG = """GREET = 0x41
stl.startup
stl.output_char GREET
stl.loop
"""

NAMESPACED_PROG = """ns a {
ns b {
GREET = 0x41
}
}
stl.startup
stl.output_char a.b.GREET
stl.loop
"""


def _assemble_with(tmp_path: Path, name: str, source: str, *defines: str) -> bytes:
    fj_path = tmp_path / f"{name}.fj"
    fj_path.write_text(source)
    out_path = tmp_path / f"{name}.fjm"
    args = ["--asm", "-o", str(out_path), "-w", "32"]
    for define in defines:
        args += ["-D", define]
    assemble_run_according_to_cmd_line_args(cmd_line_args=args + [str(fj_path)])
    return out_path.read_bytes()


def test_cli_define_reaches_the_assembled_binary(tmp_path: Path) -> None:
    """the VALUE given to -D is the value the program is assembled with.

    Asserted on the .fjm bytes rather than on stdout, because the assembler is deterministic: two
    different defines must produce different binaries, and -- the control that makes the first
    assertion mean something -- the same define twice must produce the SAME binary. Without the
    second, "they differ" could be true of any two runs.

    This is also the stl-prefix-cache control: all three assemblies run in ONE process, so the
    later ones hit the cached stl prefix. A cache that served a stale override would break the
    first assertion."""
    a = _assemble_with(tmp_path, "a", DEFINE_PROG, "GREET = 0x41")
    b = _assemble_with(tmp_path, "b", DEFINE_PROG, "GREET = 0x58")
    again = _assemble_with(tmp_path, "again", DEFINE_PROG, "GREET = 0x41")
    assert a != b, "the -D value did not reach the binary"
    assert a == again, "the assembler is not deterministic -- the difference above proves nothing"


def test_cli_define_overrides_the_programs_own_declaration(tmp_path: Path) -> None:
    """the point of -D: the overridden declaration is ignored as if it had never been written.

    The proof is an EQUALITY, not merely a difference -- overriding 0x41 with 0x58 must produce
    the very same bytes as writing 0x58 in the source. The inequality is the control."""
    overridden = _assemble_with(tmp_path, "ov", DEFINE_PROG, "GREET = 0x58")
    written = _assemble_with(tmp_path, "wr", DEFINE_PROG.replace("0x41", "0x58"))
    untouched = _assemble_with(tmp_path, "un", DEFINE_PROG)
    assert overridden == written, "-D did not replace the declaration"
    assert overridden != untouched, "the two sources are identical -- the equality proves nothing"


def test_cli_define_addresses_a_namespaced_constant_by_its_full_name(tmp_path: Path) -> None:
    """a constant declared inside `ns a { ns b {` is `a.b.GREET`, and that full name is the ONLY
    way -D can reach it. The bare name is not a shorthand: it names a different (and here,
    non-existent) constant, so it is refused rather than silently applied to the wrong one."""
    overridden = _assemble_with(tmp_path, "ns_ov", NAMESPACED_PROG, "a.b.GREET = 0x58")
    written = _assemble_with(tmp_path, "ns_wr", NAMESPACED_PROG.replace("0x41", "0x58"))
    assert overridden == written

    with pytest.raises(SystemExit):
        _assemble_with(tmp_path, "ns_bare", NAMESPACED_PROG, "GREET = 0x58")


def test_cli_define_of_an_undeclared_constant_is_refused(tmp_path: Path) -> None:
    """-D may only override. A define that never meets a declaration is a typo, and accepting it
    silently is what makes a misspelled -D look exactly like a working one."""
    bare_prog = DEFINE_PROG.replace("GREET = 0x41", "").replace("GREET", "0x41")
    assert "GREET" not in bare_prog
    with pytest.raises(SystemExit):
        _assemble_with(tmp_path, "undeclared", bare_prog, "GREET = 0x41")


def test_cli_define_of_a_parser_builtin_is_refused(tmp_path: Path) -> None:
    """`w` is set by -w and is not a declaration the program made, so -D must not appear to
    override it -- that would rewrite the width in the const table while the assembler kept
    using -w."""
    with pytest.raises(SystemExit):
        _assemble_with(tmp_path, "width", DEFINE_PROG, "w = 64")


def test_cli_define_lands_after_the_stl(tmp_path: Path) -> None:
    """the defines file is inserted first among the USER files, i.e. after the stl -- so a define
    may use an stl constant. `w` is 32 here, so `w + 33` must assemble to exactly what the literal
    65 assembles to. A defines file placed before the stl could not resolve `w` at all."""
    computed = _assemble_with(tmp_path, "computed", DEFINE_PROG, "GREET = w + 33")
    literal = _assemble_with(tmp_path, "literal", DEFINE_PROG, "GREET = 65")
    assert computed == literal


def test_cli_define_is_repeatable_and_may_use_an_earlier_define(tmp_path: Path) -> None:
    """-D is `action='append'`, and the lines are written in order, so a later define sees an
    earlier one -- including that earlier one's OVERRIDDEN value, not the value the program
    declares."""
    source = "BASE = 0" + chr(10) + DEFINE_PROG
    chained = _assemble_with(tmp_path, "chained", source, "BASE = 0x40", "GREET = BASE + 1")
    literal = _assemble_with(tmp_path, "lit2", source, "BASE = 0x40", "GREET = 0x41")
    assert chained == literal


def test_cli_define_without_a_value_is_refused(tmp_path: Path) -> None:
    """a bare -D NAME is a typo, not an empty definition."""
    fj_path = tmp_path / "defines.fj"
    fj_path.write_text(DEFINE_PROG)
    with pytest.raises(SystemExit):
        assemble_run_according_to_cmd_line_args(
            cmd_line_args=["--asm", "-o", str(tmp_path / "out.fjm"), "-w", "32", "-D", "GREET", str(fj_path)]
        )


def test_cli_define_with_a_malformed_name_is_refused(tmp_path: Path) -> None:
    """the NAME half must look like a (possibly dotted) identifier. Without this check the bad
    name reaches the generated defines file and the error points at a temporary file the user
    never wrote."""
    for bad in ("2GREET", "a..b", "a.", "GREET GREET"):
        with pytest.raises(SystemExit):
            _assemble_with(tmp_path, "bad", DEFINE_PROG, bad + " = 1")



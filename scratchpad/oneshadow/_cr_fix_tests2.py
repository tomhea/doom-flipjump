

@pytest.mark.parametrize("bad_bits", [4, 7, 10])
def test_a_bad_ptr_cell_bits_is_refused_at_assemble_time(tmp_path: Path, bad_bits: int) -> None:
    """PTR_CELL_BITS is a -D knob, so its contract has to be enforced rather than only stated.
    None of these faults loudly on its own: 7 reads 0x41 back as 0x01, and 4 satisfies BOTH rules
    the comment used to give (multiple of 4, dbit+it < dw) and then wild-jumps, because the byte
    API writes two hexes into a register sized PTR_CELL_BITS/4."""
    with pytest.raises(AssertionError):
        _assemble_at(tmp_path, "programs/hexlib_tests/basics2/pointer_setters.fj", bad_bits)


def test_the_api_defines_file_actually_reaches_the_parse(tmp_path: Path) -> None:
    """flipjump.assemble() takes defines_file, and the CLI is not the only caller. The wrapper builds
    file_tuples from fj_file_paths alone, so without an explicit insert the parameter is accepted and
    silently ignored -- the worst failure mode for an override, because the build looks fine and is
    simply not overridden."""
    prog = tmp_path / "prog.fj"
    prog.write_text("GREET = 0x5" + chr(10) + "stl.startup" + chr(10)
                    + "hex.print_as_digit g, 0" + chr(10) + "stl.loop" + chr(10)
                    + "  g: hex.hex GREET" + chr(10))
    defines = tmp_path / "_defines.fj"
    defines.write_text("GREET = 0x8" + chr(10))

    plain, overridden = tmp_path / "plain.fjm", tmp_path / "ov.fjm"
    assemble([prog], plain, memory_width=32, print_time=False)
    assemble([prog], overridden, memory_width=32, print_time=False, defines_file=defines)
    assert plain.read_bytes() != overridden.read_bytes(), "defines_file was ignored"

    prog.write_text(prog.read_text().replace("0x5", "0x8"))
    written = tmp_path / "written.fjm"
    assemble([prog], written, memory_width=32, print_time=False)
    assert overridden.read_bytes() == written.read_bytes(), "the override is not the written value"

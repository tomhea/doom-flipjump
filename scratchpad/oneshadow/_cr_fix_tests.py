

def test_cli_define_repeated_for_one_name_still_needs_a_declaration(tmp_path: Path) -> None:
    """a define may not satisfy ITSELF. The defines file is parsed before the stl, so the only way a
    non-builtin name can already be in the const table while reading it is that an earlier line of
    the same file put it there -- and treating that as "already declared" silently turns off the
    override-only rule for any name given twice. A misspelled -D repeated is still a misspelled -D."""
    with pytest.raises(FlipJumpParsingException):
        _assemble_with(tmp_path, "twice", DEFINE_PROG, "TYPO = 12", "TYPO = 16")


def test_cli_define_repeated_for_a_declared_name_takes_the_last(tmp_path: Path) -> None:
    """the control for the test above: repeating -D is only an error when nothing declares the name.
    On a name the program does declare, the last -D wins, exactly as two lines of one file would."""
    twice = _assemble_with(tmp_path, "lastwins", DEFINE_PROG, "GREET = 0x58", "GREET = 0x41")
    once = _assemble_with(tmp_path, "onceonly", DEFINE_PROG, "GREET = 0x41")
    assert twice == once


def test_cli_define_refusal_names_the_defines_file(tmp_path: Path) -> None:
    """the error must point at the -D, not at whatever file happened to be parsed last. syntax_error
    formats its position from a module global that by then holds the user's program, so without
    re-pointing it the message names their source at a line number taken from the defines file --
    a position that exists and is wrong, which is the worst kind."""
    fj_path = tmp_path / "prog.fj"
    fj_path.write_text(DEFINE_PROG)
    with pytest.raises(FlipJumpParsingException) as excinfo:
        assemble_run_according_to_cmd_line_args(
            cmd_line_args=["--asm", "-o", str(tmp_path / "out.fjm"), "-w", "32",
                           "-D", "NOPE = 5", str(fj_path)]
        )
    message = str(excinfo.value)
    assert "_defines.fj" in message, message
    assert "prog.fj" not in message, message

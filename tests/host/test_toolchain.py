from doomfj.build import build

def test_build_reports_flat(tmp_path):
    m = build(out_fjm=tmp_path / "hello.fjm", metrics=tmp_path / "metrics.json")
    assert m["storage_mode"] == "flat"      # FAILs against the 'STUB' sentinel, PASSes on the real build
    assert m["op_counter"] > 0
    assert m["fjm_bytes"] > 0

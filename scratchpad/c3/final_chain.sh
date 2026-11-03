cd /c/Users/tomhe/Documents/doom-c-doors
echo "== fj tests"
PYTHONPATH=src python -m pytest tests/fj/test_doors_c3_fj.py tests/fj/test_shot_doors_fj.py tests/fj/test_doors_e1m2_fj.py tests/fj/test_door_reversal_fj.py tests/fj/test_switch_tex_fj.py tests/fj/test_player_shot_fj.py tests/fj/test_aim_record_fj.py tests/fj/test_dead_guards_fj.py -q -p no:cacheprovider --tb=short 2>&1 | tail -15
echo "== E1M2 identity"
bash scratchpad/c3/e1m2_identity.sh 2>&1 | tail -5
echo "== emit_baseline E1M1"
PYTHONPATH=src python scratchpad/cr/emit_baseline.py --check 2>&1 | tail -15

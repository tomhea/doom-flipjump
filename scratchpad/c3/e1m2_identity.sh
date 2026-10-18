# C3 rule 3 for E1M2: the game tier's emitted parts at the base (c7d998eb, the m8-episode C3 merged) vs this tree
set -e
cd /c/Users/tomhe/Documents/doom-c-doors
rm -rf scratchpad/c3/base && mkdir -p scratchpad/c3/base && git archive c7d998eb src | tar -x -C scratchpad/c3/base
BW=$(cygpath -w "$PWD/scratchpad/c3/base/src"); MW=$(cygpath -w "$PWD/src")
python scratchpad/c3/parts_hash.py "$BW" E1M2 scratchpad/c3/e1m2_base.json
python scratchpad/c3/parts_hash.py "$MW" E1M2 scratchpad/c3/e1m2_c3.json
python scratchpad/c3/parts_hash.py --cmp scratchpad/c3/e1m2_base.json scratchpad/c3/e1m2_c3.json

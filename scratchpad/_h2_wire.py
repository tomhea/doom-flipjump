"""Rebuild HOISTED_SCRATCH_DECLS = round 1 (fixed) + whatever round 2 currently holds."""
import io
d1=[l.strip().rstrip(',').strip('"') for l in open('scratchpad/_hoist_decls.txt') if l.startswith('    "')]
d2=[l.strip().rstrip(',').strip('"') for l in open('scratchpad/_h2_decls.txt') if l.startswith('    "')]
assert len(d1)==158, len(d1)
names=[d.split(':')[0] for d in d1+d2]
assert len(names)==len(set(names)), "DUPLICATE NAMES"
body=['    # ROUND 1: single-instantiation macros (exact by construction)']
body+=['    "%s",' % d for d in d1]
if d2:
    body+=['','    # ROUND 2 (under bisection): multi-instantiation macros sharing one cell each']
    body+=['    "%s",' % d for d in d2]
p='src/doomfj/wall_renderer.py'
s=io.open(p,encoding='utf-8').read()
i=s.index('HOISTED_SCRATCH_DECLS = ['); j=s.index('\n]\n', i)+3
s=s[:i]+'HOISTED_SCRATCH_DECLS = [\n'+"\n".join(body)+'\n]\n'+s[j:]
io.open(p,'w',encoding='utf-8',newline='\n').write(s)
print("wired: %d round-1 + %d round-2 = %d globals" % (len(d1),len(d2),len(d1)+len(d2)))

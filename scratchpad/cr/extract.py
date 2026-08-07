import json

RAW = (r'C:\Users\tomhe\AppData\Local\Temp\claude\C--Users-tomhe-Documents-doom-flipjump'
       r'\c200871e-9a8b-468d-9bda-db1f10a6e185\tasks\wfx5ac46s.output')
raw = open(RAW, encoding='utf-8', errors='replace').read()
i = raw.find('{')
data = json.loads(raw[i:raw.rfind('}') + 1])['result']
conf = data['confirmed']
need = [f for f in conf if f.get('v_needs_change')]
notes = [f for f in conf if not f.get('v_needs_change')]
print('units', data['reviewed_units'], '| raw findings', data['total_findings'],
      '| confirmed', len(conf), '| needing change', len(need))
json.dump(need, open('scratchpad/cr/fix_queue.json', 'w', encoding='utf-8'), indent=1)
json.dump(notes, open('scratchpad/cr/notes.json', 'w', encoding='utf-8'), indent=1)
print()
print('=== FIX QUEUE ===')
for f in need:
    print('[%s/%s] %s:%s (%s)' % (f['severity'], f['rule'], f['file'], f['line'], f['unit']))
    print('   ', f['claim'][:250])
    print()
print('=== NOTES (confirmed, no change needed) ===')
for f in notes:
    print('[%s/%s] %s:%s: %s' % (f['severity'], f['rule'], f['file'], f['line'],
                                 f['claim'][:140]))

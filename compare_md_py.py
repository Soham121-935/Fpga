import verify_pcb2

with open('../../CONNECTIONS.md', 'r') as f:
    md_content = f.read()
    
expected_md = {}
for line in md_content.split('\n'):
    if line.startswith('| `'):
        parts = [p.strip() for p in line.split('|')]
        if len(parts) >= 4:
            net_name = parts[1].replace('`', '')
            pins = parts[3].split()
            for p in pins:
                if '.' in p:
                    ref, pin = p.split('.')
                    expected_md[(ref, pin)] = net_name

diff1 = set(expected_md.items()) - set(verify_pcb2.expected.items())
diff2 = set(verify_pcb2.expected.items()) - set(expected_md.items())
print('MD - PY len:', len(diff1))
print('PY - MD len:', len(diff2))

if diff1:
    print('Example MD - PY:', list(diff1)[:5])
if diff2:
    print('Example PY - MD:', list(diff2)[:5])

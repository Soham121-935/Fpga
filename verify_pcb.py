import re

with open('sv16_board.kicad_pcb', 'r') as f:
    content = f.read()
    
# Let's find all footprints and their pads
# Format might be (footprint "..." ... (pad "1" ... (net 3 "VCC")) )
# Actually let's just see what is in the file.
print("footprint in file:", "footprint" in content)
print("U1 in file:", "U1" in content)
print("fp_text in file:", "fp_text" in content)
print("net in file:", "(net " in content)

# try to find anything that looks like a footprint reference
refs = set(re.findall(r'"([A-Z]+\d+)"', content))
print("Found possible refs:", [r for r in refs if r.startswith('U') or r.startswith('R') or r.startswith('C')])

import re
import sys
from generate_schematic import NETLIST

# Build expected mapping: (ref, pin) -> net_name
expected = {}
for net, pins_str in NETLIST.items():
    for p in pins_str.split():
        if '.' in p:
            ref, pin = p.split('.')
            expected[(ref, pin)] = net
        else:
            print(f"Warning: pin format {p} in net {net}")

# Parse KiCad PCB file
with open('sv16_board.kicad_pcb', 'r', encoding='utf-8') as f:
    pcb_content = f.read()

# Extract footprints
# In KiCad 6/7/8, footprint blocks look like (footprint "lib:name" ... )
# and they span across multiple lines. We can use a simpler approach:
# Split by "(footprint" (and skip the first part which is before any footprint)
footprints = pcb_content.split("(footprint")[1:]

mismatches = []
missing_in_pcb = []
found_in_pcb = {}

for fp in footprints:
    # Find reference
    # Look for (property "Reference" "REF" or similar
    ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', fp)
    if not ref_match:
        # KiCad sometimes uses (fp_text reference "REF"
        ref_match = re.search(r'\(fp_text\s+reference\s+"([^"]+)"', fp)
        
    if not ref_match:
        continue
    
    ref = ref_match.group(1)
    
    # Find all pads in this footprint
    # Pads look like: (pad "1" smd rect (at ...) ... (net 4 "3V3") ...)
    # Sometimes there is no net.
    # Note: pad might not have quotes around pin number in some older formats but usually does.
    pad_matches = re.finditer(r'\(pad\s+"([^"]+)"[^\)]*\)[^\(]*(?:\((at|size|layers|net|drill|uuid|roundrect_rratio|thermal|zone_connect|clearance|solder_mask_margin|solder_paste_margin|primitives)[^\)]*\)\s*)*(?:\(net\s+\d+\s+"([^"]+)"\))?', fp)
    
    # Actually, a safer way to parse pad's net is to just find all pad blocks
    # A pad block starts with (pad "PIN" and ends at the matching closing brace, but regex for nested braces is hard.
    # Let's just find (pad "PIN" and then look ahead for (net ID "NETNAME") before the next (pad or end of footprint.
    pads = fp.split("(pad ")[1:]
    for pad_block in pads:
        # The pin name is usually the first quoted string or token
        m = re.match(r'\"([^\"]+)\"|([^ ]+)', pad_block)
        if not m: continue
        pin = m.group(1) or m.group(2)
        
        # Look for net inside this pad block
        net_match = re.search(r'\(net\s+\d+\s+"([^"]+)"\)', pad_block)
        # Note: in kicad 6+ it's (net 14 "3V3"). In pads, it might be just (net 14 "3V3") or (net "3V3")?
        # Let's check both
        if not net_match:
            net_match = re.search(r'\(net\s+"([^"]+)"\)', pad_block)
            
        net_name = net_match.group(1) if net_match else None
        
        # Add to found
        found_in_pcb[(ref, pin)] = net_name

# Now compare
print("Verification Results:")
print("-" * 50)

errors = 0

for (ref, pin), expected_net in expected.items():
    if (ref, pin) not in found_in_pcb:
        print(f"Missing in PCB: Component {ref}, Pin {pin} (Expected Net: {expected_net})")
        errors += 1
    else:
        actual_net = found_in_pcb[(ref, pin)]
        if actual_net != expected_net:
            # Maybe the net has a different name, or is unconnected
            print(f"Mismatch on {ref}.{pin}: Expected '{expected_net}', Found '{actual_net}'")
            errors += 1

# Check for nets that are connected in PCB but shouldn't be according to CONNECTIONS.md?
# We'll skip that unless asked.

print("-" * 50)
if errors == 0:
    print("SUCCESS: All specified connections match the PCB!")
else:
    print(f"Found {errors} errors.")

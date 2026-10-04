import re
import math
import os

PCB_FILE = "sv16_board.kicad_pcb"
OUT_FILE = "sv16_board.kicad_pcb" # overwrite

def process_pcb():
    with open(PCB_FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    # We need to find all (footprint ...) blocks, extract their Ref, 
    # and update the (at X Y [rot]) part.
    
    # Let's map references to new coordinates.
    # Grouping logic:
    groups = {
        'FPGA': ['U1'],
        'Power_Input': ['J9', 'D8', 'D9', 'FB1', 'C23', 'C39'],
        'Reg_1V1': ['U6', 'R40', 'R41', 'C31', 'R38', 'R39', 'R45', 'C35', 'C33', 'D11', 'L2', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C21'],
        'Reg_3V3': ['U5', 'R48', 'R49', 'R46', 'R47', 'C38', 'L1', 'C12', 'C13', 'C14', 'C15', 'C16', 'C17', 'C18', 'C19', 'C20', 'C24', 'C25', 'C26', 'C27', 'C28', 'C29', 'C30', 'C40', 'C41'],
        'Reg_2V5': ['U7', 'R43', 'C32', 'C8', 'C9', 'C10', 'C11', 'C22', 'C42'],
        'Config_Flash': ['U2', 'R9', 'R10', 'R11', 'R12', 'R13', 'R14', 'R15', 'R8'],
        'User_Flash': ['U3', 'R16', 'R17', 'R18'],
        'USB_C': ['J8', 'U8', 'R36', 'R37'],
        'USB_UART': ['U4', 'Y2', 'C36', 'C37', 'C34', 'JP1', 'R25', 'R26', 'R21', 'R23', 'R22', 'R24'],
        'Auto_Reset': ['Q1', 'Q2', 'Q4', 'R32', 'R31', 'D1', 'R33', 'D6', 'R34', 'D7', 'R44'],
        'JTAG': ['J1', 'J2'],
        'LEDs': ['R27', 'D2', 'R28', 'D3', 'R29', 'D4', 'R30', 'D5'],
        'Exp_Headers': ['J3', 'J4', 'J5'],
        'Motor': ['J6', 'R19'],
        'Console': ['J10'],
        'Reset_Boot': ['SW1', 'R1', 'C1', 'R5', 'R6', 'R7', 'SW2', 'R2', 'R3', 'R4'],
        'Clock': ['Y1'],
        'Test_Points': ['TP1', 'TP2', 'TP3', 'TP4', 'TP5', 'TP6']
    }

    # Assign coordinates based on groups
    layout = {
        'FPGA': (80, 80),
        'Power_Input': (20, 20),
        'Reg_1V1': (40, 20),
        'Reg_3V3': (60, 20),
        'Reg_2V5': (80, 20),
        'USB_C': (100, 20),
        'USB_UART': (120, 20),
        'JTAG': (20, 140),
        'Exp_Headers': (80, 140),
        'LEDs': (140, 140),
        'Config_Flash': (40, 80),
        'User_Flash': (40, 100),
        'Auto_Reset': (120, 80),
        'Motor': (140, 80),
        'Console': (140, 100),
        'Reset_Boot': (20, 80),
        'Clock': (60, 100),
        'Test_Points': (140, 20)
    }

    ref_coords = {}
    for group, refs in groups.items():
        base_x, base_y = layout.get(group, (160, 160))
        # Distribute components in a grid around the base
        cols = 4 if len(refs) < 16 else 6
        for i, ref in enumerate(refs):
            rx = base_x + (i % cols) * 5
            ry = base_y + (i // cols) * 5
            if ref == 'U1': # FPGA is large
                rx, ry = base_x, base_y
            ref_coords[ref] = (rx, ry)

    # Find footprints and update
    # Regex logic: 
    # We want to match: (footprint "..." (layer "...") (at ... )
    # But wait, (at ...) might be further in the line.
    # The safest way is to find the reference, then trace back to the (at ...) for that footprint.
    
    # We can split the file by "(footprint "
    parts = content.split("(footprint ")
    new_parts = [parts[0]]

    for part in parts[1:]:
        # extract reference
        ref_match = re.search(r'\(fp_text reference "([^"]+)"', part)
        if ref_match:
            ref = ref_match.group(1)
            if ref in ref_coords:
                x, y = ref_coords[ref]
                # Replace the (at X Y [rot]) in the first line of the footprint
                # The first line of the part goes up to the first newline
                first_line_end = part.find('\n')
                first_line = part[:first_line_end]
                rest = part[first_line_end:]
                
                # find (at ...) in first_line
                # it could be (at X Y) or (at X Y R)
                at_match = re.search(r'\(at [^)]+\)', first_line)
                if at_match:
                    # check if it has rotation
                    old_at = at_match.group(0)
                    parts_at = old_at.strip('()').split()
                    rot = parts_at[3] if len(parts_at) > 3 else "0"
                    
                    new_at = f"(at {x:.2f} {y:.2f} {rot})"
                    first_line = first_line[:at_match.start()] + new_at + first_line[at_match.end():]
                
                part = first_line + rest
        new_parts.append(part)

    new_content = "(footprint ".join(new_parts)

    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print(f"Successfully re-arranged components in {PCB_FILE}!")

if __name__ == '__main__':
    process_pcb()

#!/usr/bin/env python3
"""
Generate KiCad 7/8 FLAT schematic (.kicad_sch) for SV-16 FPGA Board.

Components are grouped into functional blocks and placed neatly.
All connections from CONNECTIONS.md are made via global net labels
attached to every pin endpoint, ensuring 100% netlist accuracy.
"""
import os, uuid, json

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

def uid():
    return str(uuid.uuid4())

# =====================================================================
# NETLIST — verbatim from CONNECTIONS.md
# =====================================================================
NETLIST = {
    '1V1': 'C2.1 C3.1 C4.1 C5.1 C6.1 C7.1 C21.1 L2.2 R38.1 TP3.1 U1.20 U1.29 U1.38 U1.66 U1.83 U1.130',
    '2V5': 'C8.1 C9.1 C10.1 C11.1 C22.1 C42.1 TP2.1 U1.17 U1.53 U1.96 U1.132 U7.5',
    '3V3': 'C12.1 C13.1 C14.1 C15.1 C16.1 C17.1 C18.1 C19.1 C20.1 C24.1 C25.1 C26.1 C27.1 C28.1 C29.1 C30.1 C40.1 C41.1 D2.2 D3.2 D4.2 D5.2 J1.1 J2.1 J3.1 J4.1 J5.10 J10.1 L1.2 Q4.2 R1.2 R2.2 R3.2 R4.2 R5.2 R8.2 R13.2 R14.2 R15.2 R16.2 R17.2 R18.2 R19.2 R33.1 R43.1 R44.1 R46.1 TP1.1 U1.9 U1.16 U1.36 U1.43 U1.70 U1.86 U1.100 U1.122 U1.137 U2.8 U3.8 U4.16 U7.1 Y1.1 Y1.4',
    'GND': 'C1.2 C2.2 C3.2 C4.2 C5.2 C6.2 C7.2 C8.2 C9.2 C10.2 C11.2 C12.2 C13.2 C14.2 C15.2 C16.2 C17.2 C18.2 C19.2 C20.2 C21.2 C22.2 C23.2 C24.2 C25.2 C26.2 C27.2 C28.2 C29.2 C30.2 C31.2 C32.2 C34.2 C35.2 C36.2 C37.2 C39.2 C40.2 C41.2 C42.2 D7.1 D11.2 J1.7 J2.6 J2.10 J3.2 J3.15 J3.16 J3.19 J3.20 J4.2 J4.19 J5.9 J6.2 J8.A1 J8.A12 J8.B1 J8.B12 J8.S1 J8.S2 J8.S3 J8.S4 J9.2 J10.4 Q1.2 Q2.2 R6.2 R7.2 R26.2 R34.2 R36.2 R37.2 R39.2 R40.2 R45.2 R47.2 R49.2 SW1.2 SW2.2 TP4.1 U1.8 U1.15 U1.21 U1.32 U1.42 U1.65 U1.75 U1.85 U1.87 U1.101 U1.123 U1.129 U1.131 U1.138 U2.4 U3.4 U4.1 U5.1 U6.5 U6.9 U7.2 U8.2 Y1.2',
    'VM_IN': 'C23.1 C39.1 FB1.2 J6.1 R41.1 R48.1 U5.3 U6.7',
    '5V_USB': 'J3.17 J3.18 J4.20',
    'A0': 'J5.1 U1.45', 'A1': 'J5.2 R11.1 U1.46', 'A10': 'J3.5 U1.99',
    'A11': 'J3.6 U1.104', 'A12': 'J3.7 U1.105', 'A13': 'J3.8 U1.106',
    'A14': 'J3.9 U1.107', 'A15': 'J3.10 U1.108',
    'A2': 'J5.3 R10.1 U1.47', 'A3': 'J5.4 U1.48',
    'A4': 'J5.5 R12.1 U1.49', 'A5': 'J5.6 U1.50',
    'A6': 'J5.7 U1.51', 'A7': 'J5.8 U1.52',
    'A8': 'J3.3 U1.97', 'A9': 'J3.4 U1.98',
    'B0': 'J4.3 U1.135', 'B1': 'J4.4 U1.136',
    'B10': 'J4.13 U1.126', 'B11': 'J4.14 U1.127',
    'B12': 'J4.15 U1.1', 'B13': 'J4.16 U1.2',
    'B14': 'J4.17 U1.3', 'B15': 'J4.18 U1.4',
    'B2': 'J4.5 U1.139', 'B3': 'J4.6 U1.140',
    'B4': 'J4.7 U1.141', 'B5': 'J4.8 U1.142',
    'B6': 'J4.9 U1.143', 'B7': 'J4.10 U1.128',
    'B8': 'J4.11 U1.124', 'B9': 'J4.12 U1.125',
    'CC1': 'J8.A5 R36.1', 'CC2': 'J8.B5 R37.1',
    'CCLK': 'R8.1 R9.1 U1.54',
    'CFG_0': 'R6.1 U1.62', 'CFG_1': 'R5.1 U1.59', 'CFG_2': 'R7.1 U1.58',
    'D1_A': 'D1.2 R33.2', 'D6_K': 'D6.1 R34.1', 'D7_A': 'D7.2 R44.2',
    'DONE': 'J1.9 R4.1 R32.1 TP5.1 U1.56',
    'DTR_F': 'JP1.2 R25.1',
    'FB_1V1': 'R38.2 R39.1 U6.4',
    'INITN': 'J1.10 R3.1 R31.1 TP6.1 U1.55',
    'J10_RX': 'J10.3 R22.2', 'J10_TX': 'J10.2 R24.2',
    'J9_VIN': 'D8.2 J9.1',
    'PROGRAMN': 'J1.4 Q1.3 R2.1 SW2.1 U1.57',
    'Q1_G': 'Q1.1 R25.2 R26.1', 'Q2_B': 'Q2.1 R32.2',
    'Q2_C': 'D1.1 Q2.3', 'Q4_B': 'Q4.1 R31.2', 'Q4_C': 'D6.2 Q4.3',
    'TCK': 'J1.8 J2.5 U1.63', 'TDI': 'J1.3 J2.3 U1.61',
    'TDO': 'J1.2 J2.4 U1.60', 'TMS': 'J1.6 J2.2 U1.64',
    'U2_CLK': 'R9.2 U2.6', 'U2_CS': 'R12.2 R13.1 U2.1',
    'U2_DI': 'R10.2 U2.5', 'U2_DO': 'R11.2 U2.2',
    'U2_HOLD': 'R15.1 U2.7', 'U2_WP': 'R14.1 U2.3',
    'U3_HOLD': 'R18.1 U3.7', 'U3_WP': 'R17.1 U3.3',
    'U4_DTR': 'JP1.1 U4.13', 'U4_RXD': 'R23.1 U4.3',
    'U4_TXD': 'R21.1 U4.2', 'U4_V3': 'C34.1 U4.4',
    'U5_BST': 'C38.1 U5.6', 'U5_EN': 'R48.2 R49.1 U5.5',
    'U5_FB': 'R46.2 R47.1 U5.4', 'U5_SW': 'C38.2 L1.1 U5.2',
    'U6_BST': 'C33.1 U6.8', 'U6_COMP': 'C35.1 R45.1 U6.3',
    'U6_EN': 'C31.1 R41.2 U6.2', 'U6_FREQ': 'R40.1 U6.6',
    'U6_SW': 'C33.2 D11.1 L2.1 U6.1',
    'U7_EN': 'C32.1 R43.2 U7.3',
    'USB_DN': 'J8.A7 J8.B7 U8.3', 'USB_DN_F': 'U4.6 U8.4',
    'USB_DP': 'J8.A6 J8.B6 U8.1', 'USB_DP_F': 'U4.5 U8.6',
    'USB_VBUS': 'D9.2 J8.A4 J8.A9 J8.B4 J8.B9 U8.5',
    'VM_IN_RAW': 'D8.1 D9.1 FB1.1',
    'Y2_XI': 'C36.1 U4.7 Y2.1', 'Y2_XO': 'C37.1 U4.8 Y2.2',
    'clk_25m': 'U1.133 Y1.3',
    'ext_rst_n': 'C1.1 R1.1 SW1.1 U1.134',
    'flash_cs_n': 'R16.1 U1.111 U3.1', 'flash_miso': 'U1.113 U3.2',
    'flash_mosi': 'U1.112 U3.5', 'flash_sck': 'U1.110 U3.6',
    'led0': 'R27.1 U1.39', 'led0_k': 'D2.1 R27.2',
    'led1': 'R28.1 U1.40', 'led1_k': 'D3.1 R28.2',
    'led2': 'R29.1 U1.41', 'led2_k': 'D4.1 R29.2',
    'led3': 'R30.1 U1.44', 'led3_k': 'D5.1 R30.2',
    'motor_dir1': 'J6.4 U1.89', 'motor_dir2': 'J6.5 U1.102',
    'motor_fault_n': 'J6.6 R19.1 U1.103', 'pwm_out': 'J6.3 U1.88',
    'spi0_cs_n': 'J3.11 U1.115', 'spi0_miso': 'J3.14 U1.117',
    'spi0_mosi': 'J3.13 U1.116', 'spi0_sck': 'J3.12 U1.114',
    'uart_rx': 'R21.2 R22.1 U1.73', 'uart_tx': 'R23.2 R24.1 U1.74',
}

# Build reverse lookup: pin_spec -> net_name
PIN_NET = {}
for net_name, pins_str in NETLIST.items():
    for p in pins_str.split():
        PIN_NET[p] = net_name

# =====================================================================
# COMPONENT DATABASE (lib_id, footprint, value, {pin_num: pin_name})
# =====================================================================
RES_FP = {
    'R38': 'Resistor_SMD:R_0402_1005Metric',
    'R2': 'Resistor_SMD:R_0805_2012Metric', 'R3': 'Resistor_SMD:R_0805_2012Metric',
    'R4': 'Resistor_SMD:R_0805_2012Metric',
    'R27': 'Resistor_SMD:R_0805_2012Metric', 'R28': 'Resistor_SMD:R_0805_2012Metric',
    'R29': 'Resistor_SMD:R_0805_2012Metric', 'R30': 'Resistor_SMD:R_0805_2012Metric',
    'R36': 'Resistor_SMD:R_0805_2012Metric', 'R37': 'Resistor_SMD:R_0805_2012Metric',
}
for r in ['R9','R10','R11','R12','R31','R33','R34','R39','R46','R47','R49']:
    RES_FP[r] = 'Resistor_SMD:R_1206_3216Metric'

RES_VAL = {
    'R1':'10k','R2':'4.7k','R3':'4.7k','R4':'4.7k','R5':'4.7k',
    'R6':'1k','R7':'1k','R8':'1k','R9':'100','R10':'100',
    'R11':'100','R12':'100','R13':'10k','R14':'10k','R15':'10k',
    'R16':'10k','R17':'10k','R18':'10k','R19':'10k',
    'R21':'0','R22':'0','R23':'0','R24':'0','R25':'4.7k',
    'R26':'10k','R27':'470','R28':'470','R29':'470','R30':'470',
    'R31':'1k','R32':'10k','R33':'1k','R34':'1k',
    'R36':'5.1k','R37':'5.1k','R38':'12.4k','R39':'33k',
    'R40':'100k','R41':'100k','R43':'100k','R44':'1k',
    'R45':'10k','R46':'33k','R47':'10k','R48':'100k','R49':'33k',
}

CAP_DB = {
    'C1':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C2':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C3':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C4':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C5':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C6':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C7':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C8':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C9':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C10':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C11':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C12':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C13':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C14':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C15':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C16':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C17':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C18':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C19':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C20':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C21':('100u','Capacitor_Tantalum_SMD:CP_EIA-7343-31_Kemet-D'),
    'C22':('22u','Capacitor_SMD:CP_Elec_6.3x5.4'),
    'C23':('470u','Capacitor_SMD:CP_Elec_8x10.5'),
    'C24':('220u','Capacitor_SMD:CP_Elec_8x10.5'),
    'C25':('10u','Capacitor_SMD:C_0805_2012Metric'),
    'C26':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C27':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C28':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C29':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C30':('10u','Capacitor_SMD:C_0805_2012Metric'),
    'C31':('470n','Capacitor_SMD:C_0603_1608Metric'),
    'C32':('470n','Capacitor_SMD:C_0603_1608Metric'),
    'C33':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C34':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C35':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C36':('22p','Capacitor_SMD:C_0603_1608Metric'),
    'C37':('22p','Capacitor_SMD:C_0603_1608Metric'),
    'C38':('100n','Capacitor_SMD:C_0603_1608Metric'),
    'C39':('10u','Capacitor_SMD:C_0805_2012Metric'),
    'C40':('22u','Capacitor_SMD:C_1206_3216Metric'),
    'C41':('22u','Capacitor_SMD:C_1206_3216Metric'),
    'C42':('10u','Capacitor_SMD:C_0805_2012Metric'),
}

COMP = {}
for r, v in RES_VAL.items():
    COMP[r] = ('Device:R', RES_FP.get(r, 'Resistor_SMD:R_0603_1608Metric'), v, {'1':'1','2':'2'})
for c, (v, fp) in CAP_DB.items():
    lib = 'Device:C_Polarized' if 'CP_' in fp else 'Device:C'
    COMP[c] = (lib, fp, v, {'1':'1','2':'2'})

COMP['U1'] = ('sv16:LFE5U-12F-6TG144C', 'Package_QFP:LQFP-144_20x20mm_P0.5mm', 'LFE5U-12F-6TG144C', {str(i): f'P{i}' for i in range(1,145)})
COMP['U2'] = ('Memory_Flash:W25Q64JVSSIQ', 'Package_SO:SOIC-8_5.23x5.23mm_P1.27mm', 'W25Q64JVSSIQ', {'1':'/CS','2':'DO','3':'/WP','4':'GND','5':'DI','6':'CLK','7':'/HOLD','8':'VCC'})
COMP['U3'] = ('Memory_Flash:W25Q64JVSSIQ', 'Package_SO:SOIC-8_5.23x5.23mm_P1.27mm', 'W25Q64JVSSIQ', {'1':'/CS','2':'DO','3':'/WP','4':'GND','5':'DI','6':'CLK','7':'/HOLD','8':'VCC'})
COMP['U4'] = ('Interface_USB:CH340G', 'Package_SO:SOIC-16_3.9x9.9mm_P1.27mm', 'CH340G', {'1':'GND','2':'TXD','3':'RXD','4':'V3','5':'UD+','6':'UD-','7':'XI','8':'XO', '9':'CTS#','10':'DSR#','11':'RI#','12':'DCD#','13':'DTR#','14':'RTS#','15':'R232','16':'VCC'})
COMP['U5'] = ('Regulator_Switching:AP62300', 'Package_TO_SOT_SMD:SOT-23-6', 'AP62300TWU-7', {'1':'GND','2':'SW','3':'VIN','4':'FB','5':'EN','6':'BST'})
COMP['U6'] = ('Regulator_Switching:MP1584EN', 'Package_SO:SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.3mm', 'MP1584EN-LF-Z', {'1':'SW','2':'EN','3':'COMP','4':'FB','5':'GND','6':'FREQ','7':'VIN','8':'BST','9':'EP'})
COMP['U7'] = ('Regulator_Linear:LP5907MFX-2.5', 'Package_TO_SOT_SMD:SOT-23-5', 'LP5907MFX-2.5', {'1':'IN','2':'GND','3':'EN','4':'NC','5':'OUT'})
COMP['U8'] = ('Power_Protection:USBLC6-2SC6', 'Package_TO_SOT_SMD:SOT-23-6', 'USBLC6-2SC6', {'1':'IO1','2':'GND','3':'IO2','4':'IO2p','5':'VBUS','6':'IO1p'})
COMP['Y1'] = ('Oscillator:Oscillator_SMD_4Pin', 'Oscillator:Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm', '25MHz', {'1':'VCC','2':'GND','3':'OUT','4':'EN'})
COMP['Y2'] = ('Device:Crystal', 'Crystal:Crystal_HC49-4H_Vertical', '12MHz', {'1':'1','2':'2'})
COMP['Q1'] = ('Transistor_FET:2N7002', 'Package_TO_SOT_SMD:SOT-23', '2N7002', {'1':'G','2':'S','3':'D'})
COMP['Q2'] = ('Transistor_BJT:MMBT3904', 'Package_TO_SOT_SMD:SOT-23', 'MMBT3904', {'1':'B','2':'E','3':'C'})
COMP['Q4'] = ('Transistor_BJT:MMBT3906', 'Package_TO_SOT_SMD:SOT-23', 'MMBT3906', {'1':'B','2':'E','3':'C'})
for i in range(1,8):
    color = 'Green' if i <= 5 else 'Red'
    COMP[f'D{i}'] = ('Device:LED', 'LED_SMD:LED_0603_1608Metric', f'LED_{color}', {'1':'K','2':'A'})
for ref in ['D8','D9','D11']:
    COMP[ref] = ('Diode:SS34', 'Diode_SMD:D_SMA', 'SS34', {'1':'K','2':'A'})
for ref in ['L1','L2']:
    COMP[ref] = ('Device:L', 'Inductor_SMD:L_Sunlord_MWSA0518_5.4x5.2mm', '10uH', {'1':'1','2':'2'})
COMP['FB1'] = ('Device:FerriteBead', 'Inductor_SMD:L_0603_1608Metric', '600R@100MHz', {'1':'1','2':'2'})
for ref in ['SW1','SW2']:
    COMP[ref] = ('Switch:SW_Push', 'Button_Switch_THT:SW_PUSH_6mm', 'SW_Push', {'1':'1','2':'2'})
COMP['J1'] = ('Connector_Generic:Conn_01x10', 'Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical', 'JTAG', {str(i):str(i) for i in range(1,11)})
COMP['J2'] = ('Connector_Generic:Conn_02x05_Odd_Even', 'Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical', 'JTAG_ALT', {str(i):str(i) for i in range(1,11)})
COMP['J3'] = ('Connector_Generic:Conn_02x10_Odd_Even', 'Connector_PinHeader_2.54mm:PinHeader_2x10_P2.54mm_Vertical', 'EXP-A', {str(i):str(i) for i in range(1,21)})
COMP['J4'] = ('Connector_Generic:Conn_02x10_Odd_Even', 'Connector_PinHeader_2.54mm:PinHeader_2x10_P2.54mm_Vertical', 'EXP-B', {str(i):str(i) for i in range(1,21)})
COMP['J5'] = ('Connector_Generic:Conn_01x10', 'Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical', 'EXP-C', {str(i):str(i) for i in range(1,11)})
COMP['J6'] = ('Connector_Generic:Conn_01x06', 'Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical', 'MOTOR', {str(i):str(i) for i in range(1,7)})
j8_pins = {p:p for p in ['A1','A4','A5','A6','A7','A9','A12','B1','B4','B5','B6','B7','B9','B12','S1','S2','S3','S4']}
COMP['J8'] = ('Connector:USB_C_Receptacle_USB2.0', 'Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12', 'USB_C', j8_pins)
COMP['J9'] = ('Connector:Barrel_Jack', 'Connector_BarrelJack:BarrelJack_CUI_PJ-102AH_Horizontal', 'Barrel_Jack', {'1':'Tip','2':'Sleeve'})
COMP['J10'] = ('Connector_Generic:Conn_01x04', 'Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical', 'CONSOLE', {str(i):str(i) for i in range(1,5)})
COMP['JP1'] = ('Connector_Generic:Conn_01x02', 'Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical', 'DTR_JP', {'1':'1','2':'2'})
tp_nets = {'TP1':'3V3','TP2':'2V5','TP3':'1V1','TP4':'GND','TP5':'DONE','TP6':'INITN'}
for ref, net in tp_nets.items():
    COMP[ref] = ('TestPoint:TestPoint', 'TestPoint:TestPoint_Pad_D1.0mm', net, {'1':'1'})

# =====================================================================
# SYMBOL GEOMETRY HELPERS
# =====================================================================
def generic_sym_info(pins, body_w=10.16):
    """Returns dict {pin_num: (rel_x, rel_y, angle)} and row count."""
    pin_list = sorted(pins.items(), key=lambda x: (x[0] if not x[0].isdigit() else x[0].zfill(5)))
    left_pins = pin_list[:len(pin_list)//2 + len(pin_list) % 2]
    right_pins = pin_list[len(pin_list)//2 + len(pin_list) % 2:]
    max_side = max(len(left_pins), len(right_pins), 1)
    rows = max_side + 1
    if rows % 2 != 0:
        rows += 1
    half_h = (rows * 2.54) / 2
    half_w = body_w / 2
    info = {}
    for i, (pnum, _) in enumerate(left_pins):
        info[pnum] = (-(half_w + 2.54), half_h - 2.54 - i * 2.54, 180)
    for i, (pnum, _) in enumerate(right_pins):
        info[pnum] = (half_w + 2.54, half_h - 2.54 - i * 2.54, 0)
    return info, rows

def fpga_sym_info():
    """Returns dict {pin_num_str: (rel_x, rel_y, angle)} for 144-pin FPGA."""
    all_pins = list(range(1, 145))
    left   = all_pins[0:36]
    bottom = all_pins[36:72]
    right  = all_pins[72:108]
    top    = all_pins[108:144]
    half = (38 * 2.54) / 2
    info = {}
    for i, pn in enumerate(left):
        info[str(pn)] = (-(half + 2.54), half - 2.54 - i * 2.54, 180)
    for i, pn in enumerate(bottom):
        info[str(pn)] = (-half + 2.54 + i * 2.54, -(half + 2.54), 270)
    for i, pn in enumerate(right):
        info[str(pn)] = (half + 2.54, -half + 2.54 + i * 2.54, 0)
    for i, pn in enumerate(top):
        info[str(pn)] = (half - 2.54 - i * 2.54, half + 2.54, 90)
    return info

# =====================================================================
# LIB_SYMBOL GENERATORS
# =====================================================================
def make_generic_lib_sym(lib_id, pins, body_w=10.16):
    info, rows = generic_sym_info(pins, body_w)
    half_h = (rows * 2.54) / 2
    half_w = body_w / 2
    sym_name = lib_id.split(':')[-1] if ':' in lib_id else lib_id
    lines = [
        f'    (symbol "{lib_id}" (in_bom yes) (on_board yes)',
        f'      (property "Reference" "X" (at 0 {half_h+1.27:.2f} 0) (effects (font (size 1.27 1.27))))',
        f'      (property "Value" "{sym_name}" (at 0 {-(half_h+1.27):.2f} 0) (effects (font (size 1.27 1.27))))',
        f'      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
        f'      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
        f'      (symbol "{sym_name}_0_1"',
        f'        (rectangle (start {-half_w:.2f} {half_h:.2f}) (end {half_w:.2f} {-half_h:.2f})',
        f'          (stroke (width 0.254) (type default))',
        f'          (fill (type background))',
        f'        )',
        f'      )',
        f'      (symbol "{sym_name}_1_1"'
    ]
    for pnum, (px, py, angle) in info.items():
        lines.append(f'        (pin passive line (at {px:.2f} {py:.2f} {angle}) (length 2.54)')
        lines.append(f'          (name "{pins[pnum]}" (effects (font (size 1.0 1.0))))')
        lines.append(f'          (number "{pnum}" (effects (font (size 1.0 1.0))))')
        lines.append(f'        )')
    lines.append(f'      )')
    lines.append(f'    )')
    return '\n'.join(lines)

def make_fpga_lib_sym():
    lib_id = 'sv16:LFE5U-12F-6TG144C'
    sym_name = 'LFE5U-12F-6TG144C'
    info = fpga_sym_info()
    half = (38 * 2.54) / 2
    lines = [
        f'    (symbol "{lib_id}" (in_bom yes) (on_board yes)',
        f'      (property "Reference" "U" (at 0 {half+2.54:.2f} 0) (effects (font (size 1.27 1.27))))',
        f'      (property "Value" "{sym_name}" (at 0 {-(half+2.54):.2f} 0) (effects (font (size 1.27 1.27))))',
        f'      (property "Footprint" "Package_QFP:LQFP-144_20x20mm_P0.5mm" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
        f'      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
        f'      (symbol "{sym_name}_0_1"',
        f'        (rectangle (start {-half:.2f} {half:.2f}) (end {half:.2f} {-half:.2f})',
        f'          (stroke (width 0.254) (type default))',
        f'          (fill (type background))',
        f'        )',
        f'      )',
        f'      (symbol "{sym_name}_1_1"'
    ]
    for pnum, (px, py, angle) in info.items():
        lines.append(f'        (pin passive line (at {px:.2f} {py:.2f} {angle}) (length 2.54)')
        lines.append(f'          (name "P{pnum}" (effects (font (size 0.8 0.8))))')
        lines.append(f'          (number "{pnum}" (effects (font (size 0.8 0.8))))')
        lines.append(f'        )')
    lines.append(f'      )')
    lines.append(f'    )')
    return '\n'.join(lines)

# =====================================================================
# SCHEMATIC OUTPUT HELPERS
# =====================================================================
def emit_symbol(ref, x, y, rotation=0):
    """Emit a component symbol instance and return list of (pin_spec, abs_x, abs_y) for wiring."""
    lib_id, fp, val, pins = COMP[ref]
    lines = []
    lines.append(f'  (symbol (lib_id "{lib_id}") (at {x:.2f} {y:.2f} {rotation}) (unit 1)')
    lines.append(f'    (in_bom yes) (on_board yes) (dnp no)')
    lines.append(f'    (uuid {uid()})')
    lines.append(f'    (property "Reference" "{ref}" (at {x:.2f} {y - 5.08:.2f} 0) (effects (font (size 1.27 1.27))))')
    lines.append(f'    (property "Value" "{val}" (at {x:.2f} {y + 5.08:.2f} 0) (effects (font (size 1.27 1.27))))')
    lines.append(f'    (property "Footprint" "{fp}" (at {x:.2f} {y:.2f} 0) (effects (font (size 1.27 1.27)) hide))')
    lines.append(f'    (property "Datasheet" "" (at {x:.2f} {y:.2f} 0) (effects (font (size 1.27 1.27)) hide))')
    for pnum in sorted(pins.keys(), key=lambda k: k.zfill(5) if k.isdigit() else k):
        lines.append(f'    (pin "{pnum}" (uuid {uid()}))')
    lines.append(f'  )')

    # Calculate absolute pin positions
    import math
    if ref == 'U1':
        info = fpga_sym_info()
    else:
        info, _ = generic_sym_info(pins)

    pin_positions = []
    rad = math.radians(rotation)
    cos_r = round(math.cos(rad))
    sin_r = round(math.sin(rad))
    for pnum, (rel_x, rel_y, pin_angle) in info.items():
        # Apply rotation to relative position
        abs_x = x + rel_x * cos_r - (-rel_y) * sin_r
        abs_y = y + rel_x * sin_r + (-rel_y) * cos_r
        # Pin angle also rotates
        actual_angle = (pin_angle + rotation) % 360
        pin_positions.append((f'{ref}.{pnum}', abs_x, abs_y, actual_angle))

    return '\n'.join(lines), pin_positions


def emit_label(net_name, x, y, angle=0):
    """Emit a short wire stub + global label at a pin endpoint."""
    # Wire stub direction based on angle
    length = 5.08
    if angle == 0:    # label to the right
        ex, ey = x + length, y
    elif angle == 180: # label to the left
        ex, ey = x - length, y
    elif angle == 90:  # label upward
        ex, ey = x, y - length
    elif angle == 270: # label downward
        ex, ey = x, y + length
    else:
        ex, ey = x + length, y

    wire = f'  (wire (pts (xy {x:.2f} {y:.2f}) (xy {ex:.2f} {ey:.2f})) (stroke (width 0) (type default)) (uuid {uid()}))'
    label = f'  (global_label "{net_name}" (shape passive) (at {ex:.2f} {ey:.2f} {angle}) (effects (font (size 1.27 1.27))) (uuid {uid()}))'
    return wire + '\n' + label


def emit_text(text, x, y, size=3.0):
    """Emit a text annotation for section headers."""
    return f'  (text "{text}" (at {x:.2f} {y:.2f} 0) (effects (font (size {size:.1f} {size:.1f}) bold)))'


def emit_rect(x1, y1, x2, y2, label=""):
    """Emit a dashed rectangle for grouping, with optional label."""
    lines = []
    lines.append(f'  (polyline (pts (xy {x1:.2f} {y1:.2f}) (xy {x2:.2f} {y1:.2f}) (xy {x2:.2f} {y2:.2f}) (xy {x1:.2f} {y2:.2f}) (xy {x1:.2f} {y1:.2f})) (stroke (width 0.254) (type dash)) (uuid {uid()}))')
    return '\n'.join(lines)


# =====================================================================
# MAIN GENERATOR — Functional Block Layout
# =====================================================================
def generate_flat_schematic():
    lines = []
    all_pin_data = []  # Collect all pin positions

    # -- Header
    lines.append('(kicad_sch (version 20231120) (generator "sv16_gen") (generator_version "2.0")')
    lines.append(f'  (uuid {uid()})')
    lines.append('  (paper "A0")')
    lines.append('  (title_block')
    lines.append('    (title "SV-16 FPGA Board — Connected Schematic")')
    lines.append(f'    (date "2026-10-03")')
    lines.append('    (company "SV-16 Project")')
    lines.append('  )')

    # -- Lib symbols
    needed_libs = {}
    for ref, (lib_id, fp, val, pins) in COMP.items():
        if lib_id not in needed_libs or len(pins) > len(needed_libs[lib_id]):
            needed_libs[lib_id] = pins
    lines.append('  (lib_symbols')
    for lib_id, pins in sorted(needed_libs.items()):
        if lib_id == 'sv16:LFE5U-12F-6TG144C':
            lines.append(make_fpga_lib_sym())
        else:
            lines.append(make_generic_lib_sym(lib_id, pins))
    lines.append('  )')

    # ===================================================================
    # FUNCTIONAL BLOCK PLACEMENT
    # Grid: A0 paper = 1189 x 841 mm. We use mm coordinates.
    # ===================================================================

    def place(ref, x, y, rot=0):
        """Place component and collect pin data."""
        sym_text, pin_pos = emit_symbol(ref, x, y, rot)
        lines.append(sym_text)
        all_pin_data.extend(pin_pos)

    # ----- SECTION 1: FPGA (center of sheet) -----
    lines.append(emit_text("FPGA — LFE5U-12F (U1)", 253.0, 80.0))
    lines.append(emit_rect(100.0, 85.0, 410.0, 400.0))
    place('U1', 253.0, 253.0)

    # ----- SECTION 2: Power Input (top-left) -----
    lines.append(emit_text("Power Input", 440.0, 88.0))
    lines.append(emit_rect(430.0, 92.0, 630.0, 220.0))
    place('J9',  470.0, 120.0)      # Barrel jack
    place('D8',  530.0, 110.0)      # Diode from barrel
    place('D9',  530.0, 140.0)      # Diode from USB VBUS
    place('FB1', 590.0, 110.0)      # Ferrite bead -> VM_IN
    place('C23', 590.0, 160.0)      # VM_IN bulk cap
    place('C39', 590.0, 190.0)      # VM_IN cap

    # ----- SECTION 3: 1.1V Regulator (U6 MP1584) -----
    lines.append(emit_text("1.1V Regulator (U6 — MP1584)", 440.0, 228.0))
    lines.append(emit_rect(430.0, 232.0, 700.0, 400.0))
    place('U6',  500.0, 290.0)
    place('R40', 460.0, 260.0)      # FREQ
    place('R41', 460.0, 310.0)      # EN divider top
    place('C31', 460.0, 340.0)      # EN cap
    place('R38', 590.0, 260.0)      # FB_1V1 top
    place('R39', 590.0, 290.0)      # FB_1V1 bottom
    place('R45', 550.0, 330.0)      # COMP
    place('C35', 550.0, 360.0)      # COMP cap
    place('C33', 550.0, 260.0)      # BST cap
    place('D11', 500.0, 370.0)      # SW diode
    place('L2',  610.0, 370.0)      # Inductor
    # 1V1 decoupling
    place('C2',  650.0, 260.0)
    place('C3',  650.0, 280.0)
    place('C4',  650.0, 300.0)
    place('C5',  650.0, 320.0)
    place('C6',  650.0, 340.0)
    place('C7',  650.0, 360.0)
    place('C21', 650.0, 380.0)

    # ----- SECTION 4: 3.3V Regulator (U5 AP62300) -----
    lines.append(emit_text("3.3V Regulator (U5 — AP62300)", 440.0, 408.0))
    lines.append(emit_rect(430.0, 412.0, 700.0, 570.0))
    place('U5',  500.0, 460.0)
    place('R48', 460.0, 440.0)      # EN divider top
    place('R49', 460.0, 470.0)      # EN divider bottom
    place('R46', 560.0, 440.0)      # FB top
    place('R47', 560.0, 470.0)      # FB bottom
    place('C38', 540.0, 500.0)      # BST cap
    place('L1',  500.0, 530.0)      # Inductor
    # 3V3 decoupling
    place('C12', 610.0, 420.0)
    place('C13', 610.0, 437.0)
    place('C14', 610.0, 454.0)
    place('C15', 610.0, 471.0)
    place('C16', 610.0, 488.0)
    place('C17', 610.0, 505.0)
    place('C18', 610.0, 522.0)
    place('C19', 610.0, 539.0)
    place('C20', 610.0, 556.0)
    place('C24', 660.0, 420.0)
    place('C25', 660.0, 437.0)
    place('C26', 660.0, 454.0)
    place('C27', 660.0, 471.0)
    place('C28', 660.0, 488.0)
    place('C29', 660.0, 505.0)
    place('C30', 660.0, 522.0)
    place('C40', 660.0, 539.0)
    place('C41', 660.0, 556.0)

    # ----- SECTION 5: 2.5V LDO (U7 LP5907) -----
    lines.append(emit_text("2.5V LDO (U7 — LP5907)", 440.0, 578.0))
    lines.append(emit_rect(430.0, 582.0, 630.0, 690.0))
    place('U7',  500.0, 620.0)
    place('R43', 460.0, 620.0)      # EN pullup
    place('C32', 460.0, 650.0)      # EN cap
    # 2V5 decoupling
    place('C8',  570.0, 600.0)
    place('C9',  570.0, 617.0)
    place('C10', 570.0, 634.0)
    place('C11', 570.0, 651.0)
    place('C22', 570.0, 668.0)
    place('C42', 570.0, 685.0)

    # ----- SECTION 6: Config Flash (U2) with series resistors -----
    lines.append(emit_text("Config SPI Flash (U2)", 110.0, 418.0))
    lines.append(emit_rect(100.0, 422.0, 310.0, 560.0))
    place('U2',  200.0, 470.0)
    place('R9',  150.0, 430.0)      # CCLK -> CLK
    place('R10', 150.0, 455.0)      # DI series
    place('R11', 150.0, 480.0)      # DO series
    place('R12', 150.0, 505.0)      # CS series
    place('R13', 260.0, 430.0)      # CS pullup
    place('R14', 260.0, 455.0)      # WP pullup
    place('R15', 260.0, 480.0)      # HOLD pullup
    place('R8',  150.0, 540.0)      # CCLK pullup

    # ----- SECTION 7: User Flash (U3) -----
    lines.append(emit_text("User SPI Flash (U3)", 110.0, 568.0))
    lines.append(emit_rect(100.0, 572.0, 310.0, 690.0))
    place('U3',  200.0, 620.0)
    place('R16', 150.0, 600.0)      # CS pullup
    place('R17', 260.0, 600.0)      # WP pullup
    place('R18', 260.0, 630.0)      # HOLD pullup

    # ----- SECTION 8: USB-C Connector (J8) & Protection (U8) -----
    lines.append(emit_text("USB-C & ESD Protection", 720.0, 88.0))
    lines.append(emit_rect(710.0, 92.0, 900.0, 260.0))
    place('J8',  760.0, 160.0)
    place('U8',  850.0, 160.0)
    place('R36', 820.0, 210.0)      # CC1 pulldown
    place('R37', 820.0, 240.0)      # CC2 pulldown

    # ----- SECTION 9: CH340G USB-UART (U4) -----
    lines.append(emit_text("USB-UART (U4 — CH340G)", 720.0, 268.0))
    lines.append(emit_rect(710.0, 272.0, 940.0, 470.0))
    place('U4',  790.0, 340.0)
    place('Y2',  740.0, 390.0)      # Crystal
    place('C36', 740.0, 420.0)      # Crystal cap
    place('C37', 780.0, 420.0)      # Crystal cap
    place('C34', 740.0, 290.0)      # V3 cap
    place('JP1', 870.0, 340.0)      # DTR jumper
    place('R25', 870.0, 370.0)      # DTR filter
    place('R26', 870.0, 400.0)      # Q1 gate pulldown
    place('R21', 870.0, 290.0)      # UART TX series
    place('R23', 870.0, 310.0)      # UART RX series
    place('R22', 920.0, 290.0)      # UART TX to J10
    place('R24', 920.0, 310.0)      # UART RX to J10

    # ----- SECTION 10: Auto-reset circuit (Q1, Q2, Q4) -----
    lines.append(emit_text("Auto-Reset & Status", 720.0, 478.0))
    lines.append(emit_rect(710.0, 482.0, 940.0, 620.0))
    place('Q1',  770.0, 520.0)      # MOSFET for PROGRAMN
    place('Q2',  830.0, 520.0)      # NPN for DONE LED
    place('Q4',  830.0, 570.0)      # PNP for INITN LED
    place('R32', 770.0, 560.0)      # DONE -> Q2 base
    place('R31', 770.0, 590.0)      # INITN -> Q4 base
    place('D1',  890.0, 520.0)      # DONE LED
    place('R33', 890.0, 490.0)      # DONE LED resistor
    place('D6',  890.0, 570.0)      # INITN LED
    place('R34', 890.0, 600.0)      # INITN LED resistor
    place('D7',  770.0, 490.0)      # Status LED
    place('R44', 830.0, 490.0)      # Status LED resistor

    # ----- SECTION 11: JTAG (J1, J2) -----
    lines.append(emit_text("JTAG Interface", 110.0, 700.0))
    lines.append(emit_rect(100.0, 704.0, 310.0, 810.0))
    place('J1',  160.0, 760.0)
    place('J2',  250.0, 760.0)

    # ----- SECTION 12: LEDs (D2-D5, R27-R30) -----
    lines.append(emit_text("User LEDs", 330.0, 700.0))
    lines.append(emit_rect(320.0, 704.0, 480.0, 810.0))
    place('R27', 360.0, 730.0)
    place('D2',  420.0, 730.0)
    place('R28', 360.0, 750.0)
    place('D3',  420.0, 750.0)
    place('R29', 360.0, 770.0)
    place('D4',  420.0, 770.0)
    place('R30', 360.0, 790.0)
    place('D5',  420.0, 790.0)

    # ----- SECTION 13: Expansion Headers (J3, J4, J5) -----
    lines.append(emit_text("Expansion Headers", 500.0, 700.0))
    lines.append(emit_rect(490.0, 704.0, 700.0, 810.0))
    place('J3',  540.0, 760.0)
    place('J4',  620.0, 760.0)
    place('J5',  680.0, 760.0)

    # ----- SECTION 14: Motor Header (J6) -----
    lines.append(emit_text("Motor Interface", 720.0, 628.0))
    lines.append(emit_rect(710.0, 632.0, 830.0, 720.0))
    place('J6',  770.0, 680.0)
    place('R19', 770.0, 640.0)      # Fault pullup

    # ----- SECTION 15: Console UART (J10) -----
    lines.append(emit_text("Console UART", 850.0, 628.0))
    lines.append(emit_rect(840.0, 632.0, 940.0, 720.0))
    place('J10', 890.0, 680.0)

    # ----- SECTION 16: Reset & Boot Config -----
    lines.append(emit_text("Reset & Config", 110.0, 408.0, 2.5))
    # These are near the FPGA section already
    # Reset circuit
    place('SW1', 120.0, 310.0)
    place('R1',  150.0, 310.0)
    place('C1',  150.0, 340.0)
    # Boot config
    place('R5',  120.0, 370.0)      # CFG_1
    place('R6',  150.0, 370.0)      # CFG_0
    place('R7',  180.0, 370.0)      # CFG_2
    # PROGRAMN button
    place('SW2', 120.0, 280.0)
    place('R2',  150.0, 280.0)

    # ----- SECTION 17: Clock (Y1) -----
    lines.append(emit_text("25 MHz Clock", 20.0, 228.0))
    lines.append(emit_rect(10.0, 232.0, 95.0, 310.0))
    place('Y1',  55.0, 270.0)

    # ----- SECTION 18: Test Points -----
    lines.append(emit_text("Test Points", 20.0, 88.0))
    lines.append(emit_rect(10.0, 92.0, 95.0, 220.0))
    place('TP1', 55.0, 115.0)
    place('TP2', 55.0, 135.0)
    place('TP3', 55.0, 155.0)
    place('TP4', 55.0, 175.0)
    place('TP5', 55.0, 195.0)
    place('TP6', 55.0, 215.0)

    # R3, R4 for INITN/DONE pullups (near FPGA)
    place('R3',  90.0, 370.0)
    place('R4',  90.0, 390.0)

    # ===================================================================
    # WIRING — Attach global net labels to every pin
    # ===================================================================
    for pin_spec, abs_x, abs_y, pin_angle in all_pin_data:
        if pin_spec in PIN_NET:
            net_name = PIN_NET[pin_spec]
            # Choose label direction opposite to pin direction
            # pin_angle is the direction the pin points OUT from the body
            # Label should extend in the same direction (away from body)
            label_angle = pin_angle
            lines.append(emit_label(net_name, abs_x, abs_y, label_angle))

    lines.append(')')
    return '\n'.join(lines)


def generate_project():
    proj = {
        "meta": {"filename": "sv16_board.kicad_pro", "version": 1},
        "net_settings": {
            "classes": [{"name": "Default", "clearance": 0.2, "track_width": 0.25, "via_diameter": 0.8, "via_drill": 0.4}]
        },
        "schematic": {"drawing": {"default_line_thickness": 6, "default_text_size": 50}}
    }
    return json.dumps(proj, indent=2)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Generating organized schematic with net labels...")
    sch_content = generate_flat_schematic()
    sch_path = os.path.join(OUT_DIR, 'sv16_board.kicad_sch')
    with open(sch_path, 'w', encoding='utf-8') as f:
        f.write(sch_content)
    pro_path = os.path.join(OUT_DIR, 'sv16_board.kicad_pro')
    with open(pro_path, 'w', encoding='utf-8') as f:
        f.write(generate_project())
    print(f"Done! Schematic saved to {sch_path}")
    print(f"Project file saved to {pro_path}")


if __name__ == '__main__':
    main()

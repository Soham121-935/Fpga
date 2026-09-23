#!/usr/bin/env python3
"""
SV-16 Rev A — Interactive Web Dashboard & Real-Time SoC Simulator
Hosts a web-based visualization GUI to observe the SV-16 16-bit processor:
- Real-time CPU register values (R0-R7, PC, SP, SR, IR)
- Status Register flags (Z, C, N, V, IE)
- GPIO Pin states (Status LEDs and Motor Direction pins)
- Live PWM waveform generator and duty cycle monitor
- Interactive DC Motor animation (speed and direction)
- Assembly code inspector and step/run execution controls
"""

import http.server
import socketserver
import json
import os
import sys

PORT = 8080

# Import SV-16 software simulator
sys.path.insert(0, os.path.dirname(__file__))
from sv16_sim import SV16Simulator

sim = SV16Simulator()
sim.load_hex("firmware/bootrom.hex")

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SV-16 Rev A — 16-Bit FPGA Microcontroller Dashboard</title>
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --accent: #38bdf8;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --border: #334155;
            --success: #22c55e;
            --danger: #ef4444;
            --led-on: #ef4444;
            --led-off: #334155;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; }
        body { background: var(--bg-color); color: var(--text-main); padding: 20px; }
        header { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid var(--border); padding-bottom: 15px; margin-bottom: 20px; }
        h1 { font-size: 1.5rem; color: var(--accent); }
        .subtitle { font-size: 0.85rem; color: var(--text-muted); }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px; margin-bottom: 20px; }
        .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3); }
        .card-title { font-size: 1rem; color: var(--accent); margin-bottom: 12px; border-bottom: 1px solid var(--border); padding-bottom: 6px; display: flex; justify-content: space-between; }
        .reg-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
        .reg-table td { padding: 4px 8px; border-bottom: 1px solid #283548; }
        .reg-name { color: var(--text-muted); font-weight: bold; width: 40%; }
        .reg-val { font-family: monospace; color: #a5f3fc; text-align: right; }
        .flags-grid { display: flex; gap: 8px; justify-content: space-around; margin: 10px 0; }
        .flag-box { text-align: center; padding: 6px 12px; border-radius: 4px; background: #0f172a; border: 1px solid var(--border); }
        .flag-box.active { background: var(--accent); color: #0f172a; font-weight: bold; }
        .leds { display: flex; gap: 15px; justify-content: center; margin: 15px 0; }
        .led-wrap { text-align: center; font-size: 0.75rem; color: var(--text-muted); }
        .led-circle { width: 26px; height: 26px; border-radius: 50%; background: var(--led-off); margin-bottom: 4px; border: 2px solid #475569; transition: all 0.2s; }
        .led-circle.on { background: var(--led-on); box-shadow: 0 0 12px var(--led-on); border-color: #fca5a5; }
        .motor-box { text-align: center; padding: 15px; }
        .motor-rotor {
            width: 100px; height: 100px; border-radius: 50%; border: 6px dashed #38bdf8;
            margin: 0 auto 15px auto; transition: transform 0.1s linear;
        }
        .controls { display: flex; gap: 10px; margin-bottom: 20px; }
        button {
            background: #0284c7; color: white; border: none; padding: 10px 18px; border-radius: 6px;
            font-size: 0.9rem; font-weight: bold; cursor: pointer; transition: background 0.2s;
        }
        button:hover { background: #0369a1; }
        button.secondary { background: #334155; }
        button.secondary:hover { background: #475569; }
        .pwm-wave { height: 40px; background: #0b1120; border: 1px solid var(--border); border-radius: 4px; margin: 10px 0; position: relative; overflow: hidden; }
        .pwm-bar { height: 100%; background: #38bdf8; opacity: 0.7; }
        .asm-code { background: #0b1120; border: 1px solid var(--border); border-radius: 6px; padding: 10px; font-size: 0.8rem; font-family: monospace; max-height: 240px; overflow-y: auto; color: #cbd5e1; }
        .asm-code span.active-line { background: #0369a1; color: white; display: block; border-radius: 2px; }
    </style>
</head>
<body>

    <header>
        <div>
            <h1>SV-16 Rev A — 16-Bit FPGA Microcontroller</h1>
            <div class="subtitle">Target: Lattice ECP5 LFE5U-12F-6TG144C | Clock: 25.0 MHz</div>
        </div>
        <div>
            <span style="color: var(--success); font-weight: bold;">● SIMULATION ACTIVE</span>
        </div>
    </header>

    <div class="controls">
        <button onclick="runStep()">Step 1 Cycle</button>
        <button onclick="runCycles(10)">Run 10 Cycles</button>
        <button onclick="runCycles(100)">Run 100 Cycles</button>
        <button onclick="runCycles(1000)">Run 1000 Cycles</button>
        <button class="secondary" onclick="resetSim()">Reset System</button>
    </div>

    <div class="grid">
        <!-- Card 1: Core Registers -->
        <div class="card">
            <div class="card-title">CPU Architectural Registers <span>16-Bit RISC</span></div>
            <table class="reg-table">
                <tr><td class="reg-name">PC (Program Counter)</td><td class="reg-val" id="val-pc">0x0000</td></tr>
                <tr><td class="reg-name">SP (Stack Pointer)</td><td class="reg-val" id="val-sp">0x1FFE</td></tr>
                <tr><td class="reg-name">SR (Status Register)</td><td class="reg-val" id="val-sr">0x0000</td></tr>
                <tr><td class="reg-name">R0</td><td class="reg-val" id="val-r0">0x0000</td></tr>
                <tr><td class="reg-name">R1</td><td class="reg-val" id="val-r1">0x0000</td></tr>
                <tr><td class="reg-name">R2</td><td class="reg-val" id="val-r2">0x0000</td></tr>
                <tr><td class="reg-name">R3</td><td class="reg-val" id="val-r3">0x0000</td></tr>
                <tr><td class="reg-name">R4</td><td class="reg-val" id="val-r4">0x0000</td></tr>
                <tr><td class="reg-name">R5</td><td class="reg-val" id="val-r5">0x0000</td></tr>
                <tr><td class="reg-name">R6</td><td class="reg-val" id="val-r6">0x0000</td></tr>
                <tr><td class="reg-name">R7</td><td class="reg-val" id="val-r7">0x0000</td></tr>
            </table>

            <div style="margin-top: 15px; font-size: 0.8rem; color: var(--text-muted); font-weight: bold;">FLAGS (SR)</div>
            <div class="flags-grid">
                <div class="flag-box" id="flag-z">Z (Zero)</div>
                <div class="flag-box" id="flag-c">C (Carry)</div>
                <div class="flag-box" id="flag-n">N (Negative)</div>
                <div class="flag-box" id="flag-v">V (Overflow)</div>
            </div>
        </div>

        <!-- Card 2: Hardware Peripherals -->
        <div class="card">
            <div class="card-title">Peripherals & FPGA Pin Outputs <span>Memory-Mapped</span></div>

            <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 6px;">GPIO Status LEDs (Pins P38–P41, Active-Low)</div>
            <div class="leds">
                <div class="led-wrap"><div class="led-circle" id="led-0"></div>LED0</div>
                <div class="led-wrap"><div class="led-circle" id="led-1"></div>LED1</div>
                <div class="led-wrap"><div class="led-circle" id="led-2"></div>LED2</div>
                <div class="led-wrap"><div class="led-circle" id="led-3"></div>LED3</div>
            </div>

            <table class="reg-table" style="margin-top: 10px;">
                <tr><td class="reg-name">GPIO_DIR (0xF011)</td><td class="reg-val" id="val-gpio-dir">0x0000</td></tr>
                <tr><td class="reg-name">GPIO_DATA (0xF010)</td><td class="reg-val" id="val-gpio-data">0x0000</td></tr>
                <tr><td class="reg-name">PWM_PERIOD (0xF030)</td><td class="reg-val" id="val-pwm-period">1000</td></tr>
                <tr><td class="reg-name">PWM_DUTY (0xF031)</td><td class="reg-val" id="val-pwm-duty">0</td></tr>
                <tr><td class="reg-name">PWM_CTRL (0xF032)</td><td class="reg-val" id="val-pwm-ctrl">0x0000</td></tr>
            </table>

            <div style="margin-top: 15px; font-size: 0.85rem; color: var(--text-muted);">PWM Pulse Output (Pin P100) — <span id="pwm-pct">0.0%</span> Duty</div>
            <div class="pwm-wave">
                <div class="pwm-bar" id="pwm-bar" style="width: 0%;"></div>
            </div>
        </div>

        <!-- Card 3: DC Motor Actuation -->
        <div class="card">
            <div class="card-title">External Motor Actuation <span>Driver Demonstration</span></div>
            <div class="motor-box">
                <div class="motor-rotor" id="rotor"></div>
                <div style="font-size: 1.1rem; font-weight: bold;" id="motor-state">STOPPED</div>
                <div style="font-size: 0.85rem; color: var(--text-muted); margin-top: 6px;" id="motor-dir">DIR: Coast (DIR1=0, DIR2=0)</div>
                <div style="font-size: 0.85rem; color: #38bdf8; margin-top: 4px;" id="motor-speed">Speed: 0.0 RPM</div>
            </div>
        </div>
    </div>

    <!-- Assembly Code & Execution View -->
    <div class="card">
        <div class="card-title">SV-16 Active Boot Firmware (firmware/examples/motor_test.s)</div>
        <div class="asm-code" id="asm-listing">
; SV-16 Rev A Bootloader & Motor Control Program
.ORG 0x0000
0x0000: LDI R0, 0xF011      ; GPIO_DIR
0x0002: LDI R1, 0x003F      ; Lower 6 pins output (LEDs + DIR1/DIR2)
0x0004: STORE R1, [R0 + 0]
0x0005: LDI R0, 0xF010      ; GPIO_DATA
0x0007: LDI R1, 0x0001      ; Turn on LED0
0x0009: STORE R1, [R0 + 0]
0x000A: LDI R0, 0xF030      ; PWM0_PERIOD
0x000C: LDI R1, 1250        ; 20 kHz carrier frequency
0x000E: STORE R1, [R0 + 0]
0x000F: LDI R0, 0xF012      ; GPIO_SET
0x0011: LDI R1, 0x0010      ; Set DIR1 (Pin 4) Forward
0x0013: STORE R1, [R0 + 0]
0x0014: LDI R0, 0xF031      ; PWM0_DUTY
0x0016: LDI R1, 625         ; 50% Duty cycle
0x0018: STORE R1, [R0 + 0]
0x0019: LDI R0, 0xF032      ; PWM0_CTRL
0x001B: LDI R1, 1           ; Enable PWM
0x001D: STORE R1, [R0 + 0]
0x001E: main_loop: NOP
0x001F: NOP
0x0020: JMP main_loop
        </div>
    </div>

    <script>
        let motorAngle = 0;
        let motorInterval = null;

        function updateUI(data) {
            document.getElementById('val-pc').innerText = '0x' + data.pc.toString(16).padStart(4, '0').toUpperCase();
            document.getElementById('val-sp').innerText = '0x' + data.sp.toString(16).padStart(4, '0').toUpperCase();
            document.getElementById('val-sr').innerText = '0x' + data.sr.toString(16).padStart(4, '0').toUpperCase();

            for (let i = 0; i < 8; i++) {
                document.getElementById('val-r' + i).innerText = '0x' + data.regs[i].toString(16).padStart(4, '0').toUpperCase();
            }

            // Flags
            document.getElementById('flag-z').className = (data.sr & 1) ? 'flag-box active' : 'flag-box';
            document.getElementById('flag-c').className = (data.sr & 2) ? 'flag-box active' : 'flag-box';
            document.getElementById('flag-n').className = (data.sr & 4) ? 'flag-box active' : 'flag-box';
            document.getElementById('flag-v').className = (data.sr & 8) ? 'flag-box active' : 'flag-box';

            // GPIO & LEDs
            document.getElementById('val-gpio-dir').innerText = '0x' + data.gpio_dir.toString(16).padStart(4, '0').toUpperCase();
            document.getElementById('val-gpio-data').innerText = '0x' + data.gpio_data.toString(16).padStart(4, '0').toUpperCase();

            for (let i = 0; i < 4; i++) {
                let isOn = (data.gpio_data & (1 << i)) !== 0;
                document.getElementById('led-' + i).className = isOn ? 'led-circle on' : 'led-circle';
            }

            // PWM
            document.getElementById('val-pwm-period').innerText = data.pwm_period;
            document.getElementById('val-pwm-duty').innerText = data.pwm_duty;
            document.getElementById('val-pwm-ctrl').innerText = '0x' + data.pwm_ctrl.toString(16).padStart(4, '0').toUpperCase();

            let dutyPct = (data.pwm_period > 0) ? ((data.pwm_duty / data.pwm_period) * 100).toFixed(1) : 0;
            document.getElementById('pwm-pct').innerText = dutyPct + '%';
            document.getElementById('pwm-bar').style.width = dutyPct + '%';

            // Motor
            let dir1 = (data.gpio_data >> 4) & 1;
            let dir2 = (data.gpio_data >> 5) & 1;
            let pwmEn = (data.pwm_ctrl & 1) !== 0;

            let stateEl = document.getElementById('motor-state');
            let dirEl = document.getElementById('motor-dir');
            let speedEl = document.getElementById('motor-speed');

            if (pwmEn && dutyPct > 0) {
                if (dir1 && !dir2) {
                    stateEl.innerText = 'SPINNING FORWARD';
                    stateEl.style.color = 'var(--success)';
                    dirEl.innerText = 'DIR: Forward (DIR1=1, DIR2=0)';
                    speedEl.innerText = 'Speed: ' + (dutyPct * 25).toFixed(0) + ' RPM';
                    startMotorSpin(dutyPct * 0.15);
                } else if (!dir1 && dir2) {
                    stateEl.innerText = 'SPINNING REVERSE';
                    stateEl.style.color = '#f59e0b';
                    dirEl.innerText = 'DIR: Reverse (DIR1=0, DIR2=1)';
                    speedEl.innerText = 'Speed: ' + (dutyPct * 25).toFixed(0) + ' RPM';
                    startMotorSpin(-dutyPct * 0.15);
                } else {
                    stateEl.innerText = 'BRAKED';
                    stateEl.style.color = 'var(--danger)';
                    dirEl.innerText = 'DIR: Brake/Bypass (DIR1=' + dir1 + ', DIR2=' + dir2 + ')';
                    speedEl.innerText = 'Speed: 0.0 RPM';
                    stopMotorSpin();
                }
            } else {
                stateEl.innerText = 'STOPPED / OFF';
                stateEl.style.color = 'var(--text-muted)';
                dirEl.innerText = 'DIR: Coast (DIR1=' + dir1 + ', DIR2=' + dir2 + ')';
                speedEl.innerText = 'Speed: 0.0 RPM';
                stopMotorSpin();
            }
        }

        function startMotorSpin(stepDeg) {
            if (motorInterval) clearInterval(motorInterval);
            motorInterval = setInterval(() => {
                motorAngle = (motorAngle + stepDeg) % 360;
                document.getElementById('rotor').style.transform = `rotate(${motorAngle}deg)`;
            }, 30);
        }

        function stopMotorSpin() {
            if (motorInterval) {
                clearInterval(motorInterval);
                motorInterval = null;
            }
        }

        function fetchState() {
            fetch('/state').then(r => r.json()).then(updateUI);
        }

        function runStep() {
            fetch('/step').then(r => r.json()).then(updateUI);
        }

        function runCycles(n) {
            fetch('/run?cycles=' + n).then(r => r.json()).then(updateUI);
        }

        function resetSim() {
            fetch('/reset').then(r => r.json()).then(updateUI);
        }

        fetchState();
    </script>
</body>
</html>
"""

class DashboardHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global sim
        if self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode())
        elif self.path == '/state':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            state = {
                'pc': sim.pc,
                'sp': sim.sp,
                'sr': sim.sr,
                'regs': sim.regs,
                'gpio_dir': sim.gpio_dir,
                'gpio_data': sim.gpio_data,
                'pwm_period': sim.pwm_period,
                'pwm_duty': sim.pwm_duty,
                'pwm_ctrl': sim.pwm_ctrl,
                'cycles': sim.cycles
            }
            self.wfile.write(json.dumps(state).encode())
        elif self.path == '/step':
            sim.step()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok'}).encode())
        elif self.path.startswith('/run'):
            cycles = 10
            if 'cycles=' in self.path:
                cycles = int(self.path.split('cycles=')[1])
            for _ in range(cycles):
                sim.step()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok'}).encode())
        elif self.path == '/reset':
            sim = SV16Simulator()
            sim.load_hex("firmware/bootrom.hex")
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'reset'}).encode())
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), DashboardHandler) as httpd:
        print(f"SV-16 Web Dashboard running at http://0.0.0.0:{PORT}")
        httpd.serve_forever()

if __name__ == '__main__':
    run_server()

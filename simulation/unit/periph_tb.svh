// SV-16 Rev B — shared harness for the module-level peripheral testbenches.
//
// Include this *inside* a testbench module that declares:
//
//     logic clk;                 // driven by the tb (always #N clk = ~clk)
//     logic rst_n;
//     logic [3:0] addr;          // peripheral bus
//     logic [15:0] wdata, rdata;
//     logic req, we, ack;
//     int   checks = 0, errors = 0;
//
// It provides the standard bus transactions, the check() reporter and the
// verdict line the runner insists on (`RESULT: PASS`).  Keeping one copy of the
// harness means all the module-level suites measure the same way: a peripheral
// is driven through its real bus port, with the `req`/`ack` handshake the SoC
// uses, never by poking at internal registers.
//
// The handshake convention (identical to sv16_bus_interconnect / the peripheral
// slaves): a slave asserts `ack` one clock after `req`, for one clock; the
// caller drops `req` after the acknowledge.

// ---------------------------------------------------------------- bus access
task automatic bus_write(input logic [3:0] a, input logic [15:0] d);
    begin
        @(negedge clk);
        addr = a; wdata = d; we = 1'b1; req = 1'b1;
        do @(posedge clk); while (!ack);
        if (rdata === 16'hxxxx) $display("  [dbg] rdata is X during write");
        @(negedge clk);
        req = 1'b0; we = 1'b0;
    end
endtask

task automatic bus_read(input logic [3:0] a, output logic [15:0] d);
    begin
        @(negedge clk);
        addr = a; we = 1'b0; req = 1'b1;
        do @(posedge clk); while (!ack);
        d = rdata;
        @(negedge clk);
        req = 1'b0;
    end
endtask

// Read a register without moving the bus (used for the W1C/write-only checks
// where a read has a side effect -- the UART's DATA register pops the FIFO).
task automatic bus_peek(input logic [3:0] a, output logic [15:0] d);
    begin
        bus_read(a, d);
    end
endtask

// ---------------------------------------------------------------- reporting
task automatic check(input bit cond, input string msg);
    begin
        checks++;
        if (cond) $display("  [PASS] %s", msg);
        else begin
            errors++;
            $display("  [FAIL] %s", msg);
        end
    end
endtask

task automatic check_eq16(input logic [15:0] got, input logic [15:0] want,
                          input string what);
    begin
        checks++;
        if (got === want) $display("  [PASS] %s = 0x%04X", what, got);
        else begin
            errors++;
            $display("  [FAIL] %s = 0x%04X, expected 0x%04X", what, got, want);
        end
    end
endtask

task automatic finish_suite(input string title);
    begin
        $display("== %s: %0d checks, %0d failures ==", title, checks, errors);
        if (errors == 0) $display("RESULT: PASS");
        else             $display("RESULT: FAIL");
        $finish;
    end
endtask

// Catches a testbench that never reaches finish_suite (a hang, a missing
// acknowledgement, a state machine that wedges) instead of letting a timeout
// kill the suite silently.
task automatic suite_timeout(input longint ns);
    begin
        #ns;
        $display("  [FAIL] testbench did not finish in %0d ns", ns);
        $display("== %0d checks, %0d failures ==", checks, errors + 1);
        $display("RESULT: FAIL (timeout)");
        $finish;
    end
endtask

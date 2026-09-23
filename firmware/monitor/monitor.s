; =====================================================================
; SV-16 Rev B — ROM monitor (field firmware update / recovery console)
; =====================================================================
;
; This is the fallback the startup sequencer releases the CPU into when
; there is no usable application image in the SPI flash: blank or missing
; flash, a corrupt image, or a serial RX line held low during reset.
;
; It lives in the boot ROM (0xE000.., see rtl/sv16_rom.sv) and speaks a
; small ASCII line protocol over UART0 at the UART reset default of
; 115200 8-N-1.  No autobaud, no flow control, every command answers.
;
;   C<addr4><len4><crc4>   program `len` bytes at `addr`; the payload follows
;                          immediately as len*2 hex digits with no separator,
;                          and crc4 is the CRC16 of those `len` bytes
;   R<addr4><len4>         read bytes back as hex text
;   E<addr4>               erase the 4 KB sector containing `addr`
;   V<addr4>               CRC16 of the whole image (header + payload)
;   B                      verify the image at 0 and boot it
;   ?                      print the command list
;
; Answers:
;   +OK\r\n                accepted
;   -E0\r\n                unknown command character
;   -E1\r\n                bad hex digit in the command line
;   -E4\r\n                uploaded-bytes CRC mismatch (C)
;   -E5\r\n                flash controller did not go idle
;   -E6\r\n                boot attempt timed out
;   -E7\r\n                image rejected by the boot loader (B)
;   =<crc4>\r\n            V: image CRC16
;   .<hex>...\r\n          R: the requested bytes; C: one '.' per byte acked
;
; The host side is scripts/sv16_mon.py (`make upload FILE=...`), which packs
; the image with sv16_fwpack.py, uploads it over the same serial port and
; can verify or boot it afterwards.
;
; Register conventions (the monitor never returns to a caller, so nothing
; needs to survive a command; every subroutine preserves the registers it
; uses unless noted):
;   R0  byte / value under construction      R4  running CRC16
;   R1  string address (puts) or byte (putc) R5  image / flash base address
;   R2  loop counter                         R6, R7  scratch
;   R3  length / expected CRC
;   crc_step is the one exception: it keeps only R0 and R4 (clobbers R1, R6).
;
; Stack: BOOT_DEFAULT_SP (0x3FFE), the top of SRAM, above any image.
;
; Assembled by the Makefile into build/rom/monitor.hex, sized/checked by
; sv16_as.py, and baked into sv16_rom at synthesis time.
;
; Rev B: new firmware (ADR-013), fixed-width hex protocol matching
; scripts/sv16_mon.py.

; ------------------------------------------------------------ MMIO addresses
.EQU UART_DATA,   0xF040     ; read: RX byte   write: TX byte
.EQU UART_STAT,   0xF041     ; [0] TX ready, [1] RX valid
.EQU FLASH_CMD,   0xF060     ; write a FCMD_* code to start an operation
.EQU FLASH_STAT,  0xF061     ; [0] busy
.EQU FLASH_ALO,   0xF062     ; byte address [15:0]
.EQU FLASH_AHI,   0xF063     ; byte address [23:16]
.EQU FLASH_LEN,   0xF064     ; byte count
.EQU FLASH_DATA,  0xF065     ; write: payload byte, read: next read byte
.EQU FLASH_WRCNT, 0xF06B     ; bytes currently in the page buffer
.EQU BOOT_CTRL,   0xF0A0     ; [0] START, [3] AUTO
.EQU BOOT_STAT,   0xF0A1     ; [0] BUSY, [1] OK

; flash command codes (FCMD_* in rtl/sv16_pkg.sv)
.EQU C_WR_START,  3
.EQU C_FLUSH,     4
.EQU C_ERASE_SEC, 5

.EQU BOOT_HDR_SIZE, 32       ; bytes (sv16_pkg BOOT_HDR_SIZE)

; =====================================================================
; entry point
; =====================================================================
.ORG 0xE000
    ; UART0 resets to 115200 8-N-1 with TX and RX enabled, so banner first
    LDI R1, msg_banner
    CALL puts

; =====================================================================
; main loop: read one command character, dispatch
; =====================================================================
main:
    LDI R0, 0x002B           ; '+' prompt
    CALL putc
    CALL getc                ; R0 = command character
    MOV R6, R0
    LDI R0, 0x000D
    CMP R6, R0
    BEQ main                 ; bare CR: ignore
    LDI R0, 0x000A
    CMP R6, R0
    BEQ main                 ; bare LF: ignore

    ; -------------------------------------------------- command dispatch
    ; The branch offset is only eight bits wide and signed, so a handler that
    ; lives further than 127 words away must be reached through a JMP
    ; trampoline (BNE skips the two-word JMP).  A direct BEQ to a far handler
    ; wraps the offset around and sends the CPU out of the ROM.
    LDI R0, 0x0043           ; 'C'
    CMP R6, R0
    BNE d_r
    JMP cmd_prog
d_r:
    LDI R0, 0x0052           ; 'R'
    CMP R6, R0
    BNE d_e
    JMP cmd_read
d_e:
    LDI R0, 0x0045           ; 'E'
    CMP R6, R0
    BNE d_v
    JMP cmd_erase
d_v:
    LDI R0, 0x0056           ; 'V'
    CMP R6, R0
    BNE d_b
    JMP cmd_verify
d_b:
    LDI R0, 0x0042           ; 'B'
    CMP R6, R0
    BNE d_q
    JMP cmd_boot
d_q:
    LDI R0, 0x003F           ; '?'
    CMP R6, R0
    BNE d_bad
    JMP cmd_help
d_bad:
    LDI R1, err_badcmd
    CALL puts
    JMP main

cmd_help:
    LDI R1, msg_help
    CALL puts
    JMP main

; =====================================================================
; C<addr4><len4><crc4> + payload (see the protocol note at the top)
;
; crc4 covers exactly the bytes uploaded in this command, so the host can
; program any number of chunks (header, payload, whole image) and get a
; per-chunk integrity verdict before the flash is trusted.
; =====================================================================
cmd_prog:
    CALL get_hex4
    MOV R5, R0               ; R5 = flash byte address
    CALL get_hex4
    MOV R2, R0               ; R2 = length in bytes
    CALL get_hex4
    MOV R3, R0               ; R3 = expected CRC16 of the uploaded bytes

    MOV R7, R2               ; erase every sector the write will touch
    MOV R0, R5
    CALL erase_sectors

    ; open a write session: the controller buffers bytes and programs a
    ; page (256 B) automatically, stalling the bus while it does
    LDI R0, FLASH_CMD
    STORE R5, [R0 + 2]       ; FLASH_ADDR_LO
    STORE R2, [R0 + 4]       ; FLASH_LEN
    LDI R1, 0x0000
    STORE R1, [R0 + 3]       ; FLASH_ADDR_HI = 0 (first 64 KB)
    LDI R1, C_WR_START
    STORE R1, [R0 + 0]       ; FLASH_CMD

    MOV R7, R2               ; R7 = bytes still to receive
    LDI R4, 0xFFFF           ; R4 = running CRC16
prog_loop:
    LDI R0, 0x0000
    CMP R7, R0
    BEQ prog_done
    CALL get_hex2            ; R0 = next payload byte
    CALL crc_step            ; folds R0 into R4 (clobbers R1, R6)
    LDI R1, FLASH_DATA
    STORE R0, [R1 + 0]       ; into the flash page buffer
    LDI R0, 0x002E           ; '.' ack, also throttles the host
    CALL putc
    DEC R7, R7
    JMP prog_loop

prog_done:
    LDI R0, FLASH_CMD        ; flush a partial final page
    LDI R1, C_FLUSH
    STORE R1, [R0 + 0]
    CALL flash_wait

    CMP R4, R3               ; CRC of the bytes received vs declared
    BEQ prog_ok
    LDI R1, err_crc
    CALL puts
    JMP main
prog_ok:
    LDI R1, ok_line
    CALL puts
    JMP main

; =====================================================================
; R<addr4><len4>
; =====================================================================
cmd_read:
    CALL get_hex4
    MOV R5, R0               ; R5 = address
    CALL get_hex4
    MOV R3, R0               ; R3 = byte count
    MOV R0, R5
    CALL flash_begin         ; start the streaming read
    LDI R0, 0x003D           ; '='
    CALL putc
    MOV R2, R3
read_loop:
    LDI R0, 0x0000
    CMP R2, R0
    BEQ read_done
    CALL read_byte
    MOV R1, R0
    CALL put_hex2
    DEC R2, R2
    JMP read_loop
read_done:
    CALL newline
    JMP main

; =====================================================================
; E<addr4>
; =====================================================================
cmd_erase:
    CALL get_hex4
    MOV R7, R0
    LDI R1, 0x1000           ; one 4 KB sector
    MOV R0, R7
    CALL erase_sectors
    LDI R1, ok_line
    CALL puts
    JMP main

; =====================================================================
; V<addr4> — CRC16 over the image header plus the payload it describes
; =====================================================================
cmd_verify:
    CALL get_hex4
    MOV R5, R0
    CALL crc_image
    MOV R7, R0               ; keep the CRC: printing '=' clobbers R0
    LDI R0, 0x003D           ; '=' — putc reads its byte from R0
    CALL putc
    MOV R1, R7
    CALL put_hex4
    CALL newline
    JMP main

; =====================================================================
; B — verify the image at address 0 and run it
; =====================================================================
cmd_boot:
    LDI R0, BOOT_CTRL
    LDI R1, 0x0000
    STORE R1, [R0 + 2]       ; BOOT_SRC_LO = 0
    STORE R1, [R0 + 3]       ; BOOT_SRC_HI = 0
    LDI R1, 0x0009           ; [0] START, [3] AUTO (stay set for next reset)
    STORE R1, [R0 + 0]       ; NOTE: bit 2 is VERIFY-ONLY and must stay 0,
                             ; otherwise the loader validates the image but
                             ; never hands the CPU over to it

    LDI R7, 0x0000           ; 16-bit timeout: 65536 polls of BOOT_STAT
boot_poll:
    LDI R0, BOOT_STAT
    LOAD R1, [R0 + 0]
    LDI R0, 0x0001           ; BUSY
    AND R1, R1, R0
    BEQ boot_verdict         ; AND sets Z when the loader is idle
    DEC R7, R7
    BEQ boot_timeout
    JMP boot_poll

boot_verdict:
    LDI R0, BOOT_STAT
    LOAD R1, [R0 + 0]
    LDI R0, 0x0002           ; OK
    AND R1, R1, R0
    BEQ boot_bad
    ; the image is verified and already sitting in SRAM: hand the CPU over.
    ; Application images are linked at 0x0000 (the loader reports the entry
    ; point in BOOT_ENTRY; this ISA has no register-indirect jump, so the
    ; monitor uses the documented fixed entry address).
    LDI R1, ok_boot
    CALL puts
    JMP 0x0000

boot_bad:
    LDI R1, err_bootimg
    CALL puts
    JMP main
boot_timeout:
    LDI R1, err_boottimeout
    CALL puts
    JMP main

; =====================================================================
; console helpers
; =====================================================================

; putc — send the character in R0. Preserves R0, R1, R6.
putc:
    PUSH R1
    PUSH R6
pc_wait:
    LDI R1, UART_STAT
    LOAD R6, [R1 + 0]
    LDI R1, 0x0001           ; TX ready
    AND R6, R6, R1
    BNE pc_send
    JMP pc_wait
pc_send:
    LDI R1, UART_DATA
    STORE R0, [R1 + 0]
    POP R6
    POP R1
    RET

; getc — blocking read of one byte into R0. Preserves R1, R6, R7.
getc:
    PUSH R1
    PUSH R6
gc_wait:
    LDI R1, UART_STAT
    LOAD R6, [R1 + 0]
    LDI R1, 0x0002           ; RX valid
    AND R6, R6, R1
    BEQ gc_wait              ; nothing yet
    LDI R1, UART_DATA
    LOAD R0, [R1 + 0]        ; pop the byte
    POP R6
    POP R1
    RET

; puts — send the NUL terminated string at R1. Preserves R0-R7.
puts:
    PUSH R0
    PUSH R1
    PUSH R6
puts_loop:
    LOAD R0, [R1 + 0]
    LDI R6, 0x0000
    CMP R0, R6
    BEQ puts_done
    CALL putc
    INC R1, R1
    JMP puts_loop
puts_done:
    POP R6
    POP R1
    POP R0
    RET

; newline — CR LF
newline:
    PUSH R0
    PUSH R1
    LDI R0, 0x000D
    CALL putc
    LDI R0, 0x000A
    CALL putc
    POP R1
    POP R0
    RET

; get_hex2 — two hex digits from the console -> R0 (0..255)
get_hex2:
    PUSH R1
    PUSH R6
    PUSH R7
    CALL getc
    MOV R1, R0
    CALL hex_nibble          ; R0 = high nibble
    MOV R7, R0
    CALL getc
    MOV R1, R0
    CALL hex_nibble          ; R0 = low nibble
    LDI R6, 0x0004
    SHL R7, R7, R6
    OR R0, R0, R7
    POP R7
    POP R6
    POP R1
    RET

; get_hex4 — four hex digits -> R0 (0..65535)
get_hex4:
    PUSH R1
    PUSH R6
    PUSH R7
    CALL get_hex2
    MOV R7, R0               ; high byte
    CALL get_hex2
    MOV R6, R0               ; low byte
    LDI R1, 0x0008
    SHL R7, R7, R1
    OR R0, R6, R7
    POP R7
    POP R6
    POP R1
    RET

; hex_nibble — ASCII digit in R1 -> value in R0. On garbage: -E1 and stop.
hex_nibble:
    LDI R0, 0x0030           ; '0'
    CMP R1, R0
    BLT hn_bad
    LDI R0, 0x0039           ; '9'
    CMP R1, R0
    BGT hn_upper
    LDI R0, 0x0030
    SUB R0, R1, R0
    RET
hn_upper:
    LDI R0, 0x0041           ; 'A'
    CMP R1, R0
    BLT hn_lower
    LDI R0, 0x0046           ; 'F'
    CMP R1, R0
    BGT hn_lower
    LDI R0, 0x0037           ; 'A' - 10
    SUB R0, R1, R0
    RET
; lowercase is accepted too: the host tool and a human at a terminal should not
; disagree about what a hex digit looks like
hn_lower:
    LDI R0, 0x0061           ; 'a'
    CMP R1, R0
    BLT hn_bad
    LDI R0, 0x0066           ; 'f'
    CMP R1, R0
    BGT hn_bad
    LDI R0, 0x0057           ; 'a' - 10
    SUB R0, R1, R0
    RET
hn_bad:
    LDI R1, err_hex
    CALL puts
    JMP main                 ; leaked stack frame, harmless on a fatal error

; put_hex2 — print R1 as two hex digits. Preserves R0-R7.
put_hex2:
    PUSH R0
    PUSH R1
    PUSH R6
    MOV R6, R1
    LDI R0, 0x0004
    SHR R1, R6, R0           ; high nibble
    CALL put_nibble
    MOV R1, R6
    LDI R0, 0x000F
    AND R1, R1, R0           ; low nibble
    CALL put_nibble
    POP R6
    POP R1
    POP R0
    RET

; put_hex4 — print R1 as four hex digits. Preserves R0-R7.
put_hex4:
    PUSH R0
    PUSH R1
    PUSH R6
    MOV R6, R1
    LDI R0, 0x0008
    SHR R1, R6, R0           ; high byte
    CALL put_hex2
    LDI R0, 0x00FF
    AND R1, R6, R0           ; low byte — put_hex2 expects a byte, and an
    CALL put_hex2            ; unmasked word would corrupt the leading digit
    POP R6
    POP R1
    POP R0
    RET

; put_nibble — print R1 (0..15) as one hex digit. Preserves R0-R7.
put_nibble:
    PUSH R0
    PUSH R1
    LDI R0, 0x000A
    CMP R1, R0
    BGE pn_alpha
    LDI R0, 0x0030           ; '0'
    ADD R1, R1, R0
    JMP pn_out
pn_alpha:
    LDI R0, 0x0037           ; 'A' - 10
    ADD R1, R1, R0
pn_out:
    MOV R0, R1
    CALL putc
    POP R1
    POP R0
    RET

; =====================================================================
; flash helpers
; =====================================================================

; flash_wait — spin until the controller is idle (STAT[0] == 0).
; 65536 polls is ~10 ms at 25 MHz; after that the operation is wedged.
flash_wait:
    PUSH R0
    PUSH R1
    PUSH R7
    LDI R7, 0x0000
fw_loop:
    LDI R0, FLASH_STAT
    LOAD R1, [R0 + 0]
    LDI R0, 0x0001
    AND R1, R1, R0
    BEQ fw_done
    DEC R7, R7               ; sets Z on wrap
    BEQ fw_stuck
    JMP fw_loop
fw_stuck:
    LDI R1, err_flash
    CALL puts
    JMP main
fw_done:
    POP R7
    POP R1
    POP R0
    RET

; erase_sectors — erase every 4 KB sector touched by [R0, R0+R7).
; R0 = start byte address, R7 = byte count. Preserves R0-R7.
erase_sectors:
    PUSH R1
    PUSH R2
    PUSH R3
    PUSH R6
    MOV R6, R0               ; R6 = current sector base
    MOV R3, R7               ; R3 = bytes remaining
es_loop:
    LDI R1, 0x0000
    CMP R3, R1
    BEQ es_done
    LDI R0, FLASH_CMD
    STORE R6, [R0 + 2]       ; FLASH_ADDR_LO
    LDI R1, 0x0000
    STORE R1, [R0 + 3]       ; FLASH_ADDR_HI
    LDI R1, C_ERASE_SEC
    STORE R1, [R0 + 0]
    CALL flash_wait
    LDI R1, 0x1000
    ADD R6, R6, R1
    CMP R3, R1
    BLE es_done              ; this was the last sector
    SUB R3, R3, R1
    JMP es_loop
es_done:
    POP R6
    POP R3
    POP R2
    POP R1
    RET

; flash_begin — start a streaming read of R3 bytes from R0. Preserves all.
flash_begin:
    PUSH R0
    PUSH R1
    LDI R1, FLASH_CMD
    STORE R0, [R1 + 2]       ; FLASH_ADDR_LO
    LDI R0, 0x0000
    STORE R0, [R1 + 3]       ; FLASH_ADDR_HI
    STORE R3, [R1 + 4]       ; FLASH_LEN
    LDI R0, 0x0002           ; FCMD_READ_START
    STORE R0, [R1 + 0]
    POP R1
    POP R0
    RET

; read_byte — next byte of an active read stream -> R0. Preserves others.
read_byte:
    PUSH R1
    LDI R1, FLASH_DATA
    LOAD R0, [R1 + 0]
    POP R1
    RET

; =====================================================================
; CRC16-CCITT (poly 0x1021, init 0xFFFF) — same algorithm as the hardware
; =====================================================================

; crc_step — fold the byte in R0 into the CRC in R4. Clobbers R1 and R6.
; Branchless: mask = (crc >> 15) * poly, then crc = (crc << 1) ^ mask.
crc_step:
    PUSH R1
    PUSH R6
    LDI R1, 0x0008
    SHL R6, R0, R1           ; byte << 8
    XOR R4, R4, R6
    LDI R1, 0x0008
cs_bit:
    PUSH R1
    LDI R1, 0x000F
    SHR R6, R4, R1           ; top bit -> 0 or 1
    LDI R1, 0x1021
    MUL R6, R6, R1           ; -> 0 or the polynomial
    LDI R1, 0x0001
    SHL R4, R4, R1
    XOR R4, R4, R6
    POP R1
    DEC R1, R1
    BEQ cs_done
    JMP cs_bit
cs_done:
    POP R6
    POP R1
    RET

; crc_image — CRC16 over the 32-byte header at R5 plus its payload.
; Returns the CRC in R0. Clobbers R0-R4, R6, R7 (R5 preserved).
crc_image:
    PUSH R1
    PUSH R2
    PUSH R3
    PUSH R4
    PUSH R6
    PUSH R7
    LDI R4, 0xFFFF

    ; --- header: 32 bytes
    MOV R0, R5
    LDI R3, BOOT_HDR_SIZE
    CALL flash_begin
hdr_loop:
    CALL read_byte
    CALL crc_step
    DEC R3, R3
    BEQ ci_len
    JMP hdr_loop

    ; --- payload length: header word at byte offset 6
ci_len:
    MOV R0, R5
    LDI R1, 0x0006
    ADD R0, R0, R1
    LDI R3, 0x0002
    CALL flash_begin
    CALL read_byte
    MOV R6, R0               ; low byte of the word count
    CALL read_byte
    MOV R7, R0               ; high byte
    LDI R1, 0x0008
    SHL R7, R7, R1
    OR R7, R7, R6            ; R7 = payload words
    LDI R1, 0x0000
    CMP R7, R1
    BEQ ci_done              ; empty payload: only the header is covered
    LDI R1, 0x0001
    SHL R7, R7, R1           ; bytes = words * 2

    ; --- payload: 32 bytes past the image base
    MOV R0, R5
    LDI R1, BOOT_HDR_SIZE
    ADD R0, R0, R1
    MOV R3, R7
    CALL flash_begin
pld_loop:
    CALL read_byte
    CALL crc_step
    DEC R3, R3
    BEQ ci_done
    JMP pld_loop

ci_done:
    MOV R0, R4
    POP R7
    POP R6
    POP R4
    POP R3
    POP R2
    POP R1
    RET

; =====================================================================
; messages
; =====================================================================
msg_banner:
    .ASCIIZ "\r\nSV-16 monitor v1\r\n"

msg_help:
    .ASCIIZ "C<addr4><len4><crc4> program flash\r\n"
    .ASCIIZ "R<addr4><len4>         read flash\r\n"
    .ASCIIZ "E<addr4>               erase sector\r\n"
    .ASCIIZ "V<addr4>               CRC16 image\r\n"
    .ASCIIZ "B                      boot image at 0\r\n"
    .ASCIIZ "?                      this list\r\n"

ok_line:
    .ASCIIZ "\r\n+OK\r\n"

ok_boot:
    .ASCIIZ "\r\n+OK booting\r\n"

err_badcmd:
    .ASCIIZ "\r\n-E0\r\n"
err_hex:
    .ASCIIZ "\r\n-E1\r\n"
err_crc:
    .ASCIIZ "\r\n-E4\r\n"
err_flash:
    .ASCIIZ "\r\n-E5\r\n"
err_boottimeout:
    .ASCIIZ "\r\n-E6\r\n"
err_bootimg:
    .ASCIIZ "\r\n-E7\r\n"

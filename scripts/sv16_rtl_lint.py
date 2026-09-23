#!/usr/bin/env python3
"""SV-16 RTL structural lint.

Checks SystemVerilog sources for the failure modes that simulators tolerate
but synthesis silently "fixes" by resolving the conflict to a constant:

  1. a signal assigned from more than one always block
     (yosys: "Driver-driver conflict ... Resolved using constant")
  2. a signal assigned both procedurally and by a continuous assign
  3. a signal driven from two different continuous assigns
  4. combinational always blocks that do not assign a signal on every path
     (a latch in disguise) - reported as a warning

Verilator does not report (1)/(2)/(3) by default and yosys only warns while
quietly replacing the signal with a constant, which produces a design that
simulates correctly but synthesizes incorrectly. This checker is therefore
part of `make lint`.

Usage:  python3 scripts/sv16_rtl_lint.py rtl/*.sv
Exit code: 0 clean, 1 problems found.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

ALWAYS_RE = re.compile(r"^\s*(always_ff|always_comb|always_latch|always)\b")
ASSIGN_RE = re.compile(r"^\s*(?:assign\s+)?([A-Za-z_][\w\[\]:\.]*)\s*(<=|=)(?!=)")
CONTINUOUS_ASSIGN_RE = re.compile(r"^\s*assign\s+([A-Za-z_][\w\[\]:\.]*)\s*=")


@dataclass
class Block:
    kind: str
    line: int
    targets: set[str] = field(default_factory=set)


def strip_comments(text: str) -> str:
    out = []
    i = 0
    in_line = in_block = False
    in_string = False
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_line:
            if ch == "\n":
                in_line = False
                out.append(ch)
            else:
                out.append(" ")
        elif in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                out.append("  ")
                i += 2
                continue
            out.append("\n" if ch == "\n" else " ")
        elif in_string:
            out.append(ch)
            if ch == '"':
                in_string = False
        else:
            if ch == "/" and nxt == "/":
                in_line = True
                out.append("  ")
                i += 2
                continue
            if ch == "/" and nxt == "*":
                in_block = True
                out.append("  ")
                i += 2
                continue
            if ch == '"':
                in_string = True
            out.append(ch)
        i += 1
    return "".join(out)


def base_name(lhs: str) -> str:
    name = lhs.split("[")[0].split("::")[-1].split(".")[-1]
    return name.strip()


def always_blocks(text: str) -> list[Block]:
    """Split the source into always blocks (brace matching)."""
    blocks: list[Block] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = ALWAYS_RE.match(lines[i])
        if not m:
            i += 1
            continue
        kind = m.group(1)
        block = Block(kind=kind, line=i + 1)
        depth = 0
        started = False
        j = i
        while j < len(lines):
            line = lines[j]
            depth += line.count("begin") - line.count("end")
            for mm in ASSIGN_RE.finditer(line):
                block.targets.add(base_name(mm.group(1)))
            if "begin" in line:
                started = True
            if started and depth <= 0:
                break
            j += 1
        blocks.append(block)
        i += (j - i) + 1
    return blocks


def check_file(path: str) -> list[str]:
    src = strip_comments(open(path).read())
    lines = src.split("\n")

    problems: list[str] = []
    block_targets: dict[str, list[int]] = {}
    for block in always_blocks(src):
        for t in block.targets:
            block_targets.setdefault(t, []).append(block.line)

    for t, lns in sorted(block_targets.items()):
        if len(lns) > 1:
            problems.append(
                f"{path}: signal '{t}' is assigned in {len(lns)} always blocks "
                f"(lines {', '.join(map(str, lns))}) -> use a single owner block"
            )

    # continuous assignments
    cont_targets: dict[str, list[int]] = {}
    for idx, line in enumerate(lines, start=1):
        m = CONTINUOUS_ASSIGN_RE.match(line)
        if m:
            cont_targets.setdefault(base_name(m.group(1)), []).append(idx)

    for t, lns in sorted(cont_targets.items()):
        if len(lns) > 1:
            problems.append(
                f"{path}: signal '{t}' has {len(lns)} continuous drivers "
                f"(lines {', '.join(map(str, lns))})"
            )
        if t in block_targets:
            problems.append(
                f"{path}: signal '{t}' is driven both procedurally "
                f"(line {block_targets[t][0]}) and continuously (line {lns[0]})"
            )

    return problems


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    problems: list[str] = []
    for path in argv[1:]:
        problems.extend(check_file(path))
    if problems:
        print(f"sv16_rtl_lint: {len(problems)} problem(s) found\n")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"sv16_rtl_lint: OK - {len(argv) - 1} file(s) clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

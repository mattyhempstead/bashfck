#!/usr/bin/env python3
"""Encode Bash source using only seven distinct characters.

The generated program uses this alphabet:

    $'\\<015

Execution contract:
- Run or paste the output in Bash.
- ``$0`` must resolve to an executable Bash name or path.
- The bootstrap consumes standard input, so the original program receives EOF.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO, Optional, Sequence, TextIO

VERSION = "1.0.0"
CHARSET = frozenset("$'\\<015")
_SAFE_OCTAL_DIGITS = frozenset("015")

# These expressions are not written directly in the final seven-character
# program. The outer stage reconstructs them from octal escapes.
_MISSING_DIGIT_EXPRESSIONS = {
    "2": "$((1-(-1)))",
    "3": "$((5-1-1))",
    "4": "$((5-1))",
    "6": "$((5-(-1)))",
    "7": "$((5-(-1)-(-1)))",
}


def _check_no_nul(value: bytes) -> None:
    if b"\x00" in value:
        raise ValueError("Bash source containing NUL bytes cannot be encoded losslessly")


def encode_ansi_c_word(value: bytes) -> str:
    """Return a normal Bash ANSI-C-quoted word containing ``value``."""
    _check_no_nul(value)
    return "$'" + "".join("\\%03o" % byte for byte in value) + "'"


def encode_outer_word(value: bytes) -> str:
    """Encode a stage using only ``$'\\<015``.

    Literal alphabet characters are retained. Every other byte is represented
    by an octal escape whose digits are limited to 0, 1, and 5.
    """
    _check_no_nul(value)
    encoded_parts: list[str] = []

    for byte in value:
        character = chr(byte)

        if character in CHARSET:
            if character == "\\":
                encoded_parts.append("\\\\")
            elif character == "'":
                encoded_parts.append("\\'")
            else:
                encoded_parts.append(character)
            continue

        octal = "%03o" % byte
        if not set(octal) <= _SAFE_OCTAL_DIGITS:
            raise ValueError(
                "internal stage byte 0x%02x cannot be represented by the outer alphabet"
                % byte
            )
        encoded_parts.append("\\" + octal)

    return "$'" + "".join(encoded_parts) + "'"


def _final_eval_wrapper(program: bytes) -> bytes:
    """Return source that evaluates the original bytes exactly."""
    return b"builtin eval -- " + encode_ansi_c_word(program).encode("ascii")


def _stage_two(program: bytes) -> str:
    """Return source for a child Bash that runs the exact eval wrapper."""
    return "$0<<<" + encode_ansi_c_word(_final_eval_wrapper(program))


def build_decoder(program: bytes) -> bytes:
    """Build the intermediate decoder read by the first nested Bash."""
    _check_no_nul(program)
    target = _stage_two(program)
    pieces: list[str] = []
    literal: list[str] = []

    def flush_literal() -> None:
        if not literal:
            return
        value = "".join(literal)
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        pieces.append("$'" + escaped + "'")
        literal.clear()

    for character in target:
        expression = _MISSING_DIGIT_EXPRESSIONS.get(character)
        if expression is None:
            literal.append(character)
        else:
            flush_literal()
            pieces.append(expression)

    flush_literal()

    decoder = ("$0<<<" + "".join(pieces)).encode("ascii")

    # Fail during generation rather than emitting an invalid outer program.
    encode_outer_word(decoder)
    return decoder


def encode_program(program: bytes) -> str:
    """Return a self-decoding seven-character Bash program."""
    decoder = build_decoder(program)
    encoded = "$0<<<" + encode_outer_word(decoder)
    validate_encoded_program(encoded)
    return encoded


def validate_encoded_program(encoded_program: str) -> None:
    """Raise when output contains a character outside the seven-character set."""
    unexpected = set(encoded_program) - CHARSET
    if unexpected:
        raise ValueError(
            "encoded program contains unexpected character(s): %s"
            % "".join(sorted(unexpected))
        )


def read_input(path: Optional[str], stdin: BinaryIO) -> bytes:
    if path in (None, "-"):
        return stdin.read()
    return Path(path).read_bytes()


def write_output(path: Optional[str], value: str, stdout: TextIO) -> None:
    if path in (None, "-"):
        stdout.write(value)
        stdout.flush()
        return
    Path(path).write_text(value, encoding="ascii")


def check_bash_syntax(program: bytes, *, bash_path: str) -> None:
    result = subprocess.run(
        [bash_path, "-n"],
        input=program,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError("input is not valid Bash: %s" % message)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="encode Bash source using only the characters $'\\\\<015"
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="input Bash file, or - for stdin",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="-",
        help="output file, or - for stdout",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the input with bash -n before encoding",
    )
    parser.add_argument(
        "--bash",
        default="bash",
        help="Bash executable used by --check",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="print input and output sizes to stderr",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s " + VERSION,
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    try:
        program = read_input(args.input, sys.stdin.buffer)

        if args.check:
            check_bash_syntax(program, bash_path=args.bash)

        encoded = encode_program(program)
        write_output(args.output, encoded, sys.stdout)

        if args.stats:
            ratio = len(encoded) / len(program) if program else 0.0
            print(
                "input=%d bytes output=%d characters ratio=%.2fx alphabet=%d"
                % (len(program), len(encoded), ratio, len(set(encoded))),
                file=sys.stderr,
            )
    except (OSError, ValueError) as error:
        print("bashfck: %s" % error, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

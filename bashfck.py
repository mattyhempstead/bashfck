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
from functools import lru_cache
from itertools import product
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO, Optional, Sequence, TextIO

VERSION = "1.1.0"
CHARSET = frozenset("$'\\<015")
_SAFE_OCTAL_DIGITS = frozenset("015")
_DECIMAL_DIGITS = frozenset("0123456789")

# Arithmetic expressions may contain only bytes the outer ANSI-C word can
# reconstruct. A leading zero makes a Bash arithmetic constant octal, which
# provides especially short spellings for several missing decimal digits.
_SHIFT_EXPRESSIONS = {
    2: "1<<1",
    4: "1<<1<<1",
    8: "1<<1<<1<<1",
}
_ARITHMETIC_SEARCH_LIMIT = 5000
_MAX_GROUPED_DIGITS = 3

# Characters that can appear unquoted in the decoder's here-string word.
# Other reconstructable characters are protected with a backslash.
_UNQUOTED_DECODER_CHARACTERS = frozenset("015-@AEHIMhim")


def _check_no_nul(value: bytes) -> None:
    if b"\x00" in value:
        raise ValueError("Bash source containing NUL bytes cannot be encoded losslessly")


def encode_ansi_c_word(value: bytes) -> str:
    """Return a compact intermediate ANSI-C word containing ``value``.

    Bytes the outer decoder can reproduce directly stay literal. Other bytes
    use the shortest unambiguous octal escape.
    """
    _check_no_nul(value)
    encoded_parts: list[str] = []

    for index, byte in enumerate(value):
        character = chr(byte)

        if character == "\\":
            encoded_parts.append("\\\\")
            continue
        if character == "'":
            encoded_parts.append("\\'")
            continue
        if byte in _DIRECT_ANSI_C_BYTES:
            encoded_parts.append(character)
            continue

        octal = "%o" % byte
        next_byte = value[index + 1] if index + 1 < len(value) else None
        if (
            len(octal) < 3
            and next_byte in _DIRECT_ANSI_C_BYTES
            and chr(next_byte) in "01234567"
        ):
            octal = "%03o" % byte
        encoded_parts.append("\\" + octal)

    return "$'" + "".join(encoded_parts) + "'"


def encode_outer_word(value: bytes) -> str:
    """Encode a stage using only ``$'\\<015``.

    Literal alphabet characters are retained. Every other byte is represented
    by the shortest unambiguous octal escape limited to digits 0, 1, and 5.
    """
    _check_no_nul(value)
    encoded_parts: list[str] = []

    for index, byte in enumerate(value):
        character = chr(byte)

        if character in CHARSET:
            if character == "\\":
                encoded_parts.append("\\\\")
            elif character == "'":
                encoded_parts.append("\\'")
            else:
                encoded_parts.append(character)
            continue

        octal = "%o" % byte
        if not set(octal) <= _SAFE_OCTAL_DIGITS:
            raise ValueError(
                "internal stage byte 0x%02x cannot be represented by the outer alphabet"
                % byte
            )
        if (
            len(octal) < 3
            and index + 1 < len(value)
            and chr(value[index + 1]) in _SAFE_OCTAL_DIGITS
        ):
            octal = "%03o" % byte
        encoded_parts.append("\\" + octal)

    return "$'" + "".join(encoded_parts) + "'"


def _build_outer_encodable_bytes() -> frozenset[int]:
    return frozenset(
        byte
        for byte in range(1, 256)
        if chr(byte) in CHARSET
        or set("%o" % byte) <= _SAFE_OCTAL_DIGITS
    )


_OUTER_ENCODABLE_BYTES = _build_outer_encodable_bytes()
_DIRECT_ANSI_C_BYTES = (
    _OUTER_ENCODABLE_BYTES
    | frozenset(range(ord("0"), ord("9") + 1))
) - frozenset((ord("'"), ord("\\")))


def _build_arithmetic_literals() -> dict[int, str]:
    """Return short arithmetic literals containing only 0, 1, and 5."""
    literals: dict[int, str] = {}

    for length in range(1, 6):
        for digits in product("015", repeat=length):
            source = "".join(digits)
            if source.startswith("0"):
                value = int(source, 8)
            else:
                value = int(source, 10)

            if not 0 < value <= _ARITHMETIC_SEARCH_LIMIT:
                continue

            previous = literals.get(value)
            if previous is None or (len(source), source) < (len(previous), previous):
                literals[value] = source

    return literals


_ARITHMETIC_LITERALS = _build_arithmetic_literals()


def _build_subtraction_suffixes() -> list[Optional[str]]:
    """Find cheap ways to subtract every value in the search range."""
    suffixes: list[Optional[str]] = [None] * (_ARITHMETIC_SEARCH_LIMIT + 1)
    costs: list[Optional[int]] = [None] * (_ARITHMETIC_SEARCH_LIMIT + 1)
    suffixes[0] = ""
    costs[0] = 0
    terms = sorted(_ARITHMETIC_LITERALS.items())

    for target in range(1, _ARITHMETIC_SEARCH_LIMIT + 1):
        for value, source in terms:
            if value > target:
                break

            previous_cost = costs[target - value]
            previous_suffix = suffixes[target - value]
            if previous_cost is None or previous_suffix is None:
                continue

            # The minus sign is encoded as \055 because a digit follows it.
            candidate_cost = previous_cost + 4 + len(source)
            candidate_suffix = previous_suffix + "-" + source
            current_cost = costs[target]
            current_suffix = suffixes[target]
            if current_cost is None or (
                candidate_cost,
                len(candidate_suffix),
                candidate_suffix,
            ) < (
                current_cost,
                len(current_suffix or ""),
                current_suffix or "",
            ):
                costs[target] = candidate_cost
                suffixes[target] = candidate_suffix

    return suffixes


_SUBTRACTION_SUFFIXES = _build_subtraction_suffixes()


@lru_cache(maxsize=None)
def _outer_source_cost(source: str) -> int:
    """Return the encoded cost of source inside one outer ANSI-C word."""
    return len(encode_outer_word(source.encode("latin1"))) - len("$''")


@lru_cache(maxsize=None)
def _arithmetic_expression(value: int) -> str:
    """Return a short expression that expands to a positive decimal value."""
    if not 0 < value <= 999:
        raise ValueError("arithmetic synthesis value is outside 1..999")

    candidates: list[str] = []
    direct = _ARITHMETIC_LITERALS.get(value)
    if direct is not None:
        candidates.append(direct)

    for base, source in _ARITHMETIC_LITERALS.items():
        difference = base - value
        if not 0 <= difference <= _ARITHMETIC_SEARCH_LIMIT:
            continue
        suffix = _SUBTRACTION_SUFFIXES[difference]
        if suffix is not None:
            candidates.append(source + suffix)

    shifted = _SHIFT_EXPRESSIONS.get(value)
    if shifted is not None:
        candidates.append(shifted)

    if not candidates:
        raise ValueError("cannot synthesize arithmetic value %d" % value)

    return min(
        set(candidates),
        key=lambda expression: (
            _outer_source_cost("$((" + expression + "))"),
            len(expression),
            expression,
        ),
    )


@lru_cache(maxsize=None)
def _arithmetic_expansion(value: int) -> str:
    return "$((" + _arithmetic_expression(value) + "))"


@lru_cache(maxsize=None)
def _encode_digit_run(digits: str) -> str:
    """Return decoder source that emits a run of decimal digits."""
    costs: list[Optional[int]] = [None] * (len(digits) + 1)
    lengths: list[Optional[int]] = [None] * (len(digits) + 1)
    choices: list[Optional[tuple[str, int]]] = [None] * (len(digits) + 1)
    costs[len(digits)] = 0
    lengths[len(digits)] = 0

    for start in range(len(digits) - 1, -1, -1):
        digit = digits[start]
        one = digit if digit in _SAFE_OCTAL_DIGITS else _arithmetic_expansion(int(digit))
        next_cost = costs[start + 1]
        next_length = lengths[start + 1]
        if next_cost is None or next_length is None:
            raise ValueError("cannot encode decimal digit suffix")
        candidates = [
            (
                _outer_source_cost(one) + next_cost,
                len(one) + next_length,
                one,
                start + 1,
            )
        ]

        if digit != "0":
            stop_limit = min(len(digits), start + _MAX_GROUPED_DIGITS)
            for stop in range(start + 2, stop_limit + 1):
                expansion = _arithmetic_expansion(int(digits[start:stop]))
                suffix_cost = costs[stop]
                suffix_length = lengths[stop]
                if suffix_cost is None or suffix_length is None:
                    raise ValueError("cannot encode grouped decimal digit suffix")
                candidates.append(
                    (
                        _outer_source_cost(expansion) + suffix_cost,
                        len(expansion) + suffix_length,
                        expansion,
                        stop,
                    )
                )

        best_cost, best_length, best_source, best_stop = min(
            candidates,
            key=lambda candidate: (
                candidate[0],
                candidate[1],
                candidate[2],
                candidate[3],
            ),
        )
        costs[start] = best_cost
        lengths[start] = best_length
        choices[start] = (best_source, best_stop)

    pieces: list[str] = []
    index = 0
    while index < len(digits):
        choice = choices[index]
        if choice is None:
            raise ValueError("cannot encode decimal digit run")
        source, index = choice
        pieces.append(source)
    return "".join(pieces)


def _execution_stage(program: bytes) -> str:
    """Return source that passes the exact program to a child Bash with -c."""
    return "$0\t$'-\\143'\t" + encode_ansi_c_word(program)


def build_decoder(program: bytes) -> bytes:
    """Build the intermediate decoder read by the first nested Bash."""
    _check_no_nul(program)
    target = _execution_stage(program)
    pieces: list[str] = []
    index = 0

    while index < len(target):
        character = target[index]
        if character in _DECIMAL_DIGITS:
            stop = index + 1
            while stop < len(target) and target[stop] in _DECIMAL_DIGITS:
                stop += 1
            pieces.append(_encode_digit_run(target[index:stop]))
            index = stop
            continue

        if character == "\n":
            raise ValueError("internal execution stage contains a literal newline")
        if character in _UNQUOTED_DECODER_CHARACTERS:
            pieces.append(character)
        else:
            pieces.append("\\" + character)
        index += 1

    decoder = ("$0<<<" + "".join(pieces)).encode("latin1")

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
    if path is None or path == "-":
        return stdin.read()
    return Path(path).read_bytes()


def write_output(path: Optional[str], value: str, stdout: TextIO) -> None:
    if path is None or path == "-":
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

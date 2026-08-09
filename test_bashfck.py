#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

from bashfck import (
    CHARSET,
    _arithmetic_expansion,
    encode_ansi_c_word,
    encode_outer_word,
    encode_program,
)


BASH = os.environ.get("BASH_PATH", "bash")
ROOT = Path(__file__).resolve().parent


def run_encoded(
    program: bytes,
    *,
    prelude: bytes = b"",
) -> subprocess.CompletedProcess[bytes]:
    encoded = encode_program(program)
    command = (prelude + encoded.encode()).decode("ascii")
    return subprocess.run(
        [BASH, "--noprofile", "--norc", "-c", command],
        capture_output=True,
        check=False,
    )


class BashfckTests(unittest.TestCase):
    def test_echo_works(self) -> None:
        encoded = encode_program(b"echo works")
        self.assertLessEqual(set(encoded), CHARSET)
        self.assertEqual(len(encoded), 324)

        result = run_encoded(b"echo works")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"works\n")
        self.assertEqual(result.stderr, b"")

    def test_exit_status(self) -> None:
        result = run_encoded(b"exit 23")
        self.assertEqual(result.returncode, 23)

    def test_readme_example_uses_exactly_seven_characters(self) -> None:
        encoded = encode_program(b"echo 'Hello, World!'")
        self.assertEqual(len(encoded), 511)
        self.assertEqual(set(encoded), CHARSET)

    def test_exact_source_is_passed_as_the_c_argument(self) -> None:
        source = b'printf %s "$BASH_EXECUTION_STRING"'
        result = run_encoded(source)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, source)
        self.assertEqual(result.stderr, b"")

    def test_source_ending_in_a_backslash(self) -> None:
        result = run_encoded(b"printf '<%s>' \\")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"<>")
        self.assertEqual(result.stderr, b"")

    def test_exported_builtin_function_cannot_intercept_execution(self) -> None:
        result = run_encoded(
            b"echo payload",
            prelude=b"builtin() { echo intercepted; }\nexport -f builtin\n",
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"payload\n")
        self.assertEqual(result.stderr, b"")

    def test_primes(self) -> None:
        source = (ROOT / "examples" / "primes-under-100.sh").read_bytes()
        result = run_encoded(source)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout,
            b"2\n3\n5\n7\n11\n13\n17\n19\n23\n29\n31\n37\n41\n43\n47\n"
            b"53\n59\n61\n67\n71\n73\n79\n83\n89\n97\n",
        )

    def test_nul_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            encode_program(b"printf a\x00b")

    def test_all_non_nul_bytes_can_appear_inside_a_comment(self) -> None:
        data = bytes(range(1, 256))
        source = (
            b'printf %s "$BASH_EXECUTION_STRING"\n'
            b": <<'BASHFCK'\n"
            + data
            + b"\nBASHFCK\n:"
        )
        encoded = encode_program(source)
        self.assertLessEqual(set(encoded), CHARSET)

        result = run_encoded(source)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, source)
        self.assertEqual(result.stderr, b"")

    def test_short_octal_escapes_remain_unambiguous(self) -> None:
        self.assertEqual(encode_ansi_c_word(b" A"), "$'\\40A'")
        self.assertEqual(encode_ansi_c_word(b" 1"), "$'\\0401'")
        self.assertEqual(encode_outer_word(b"(A"), "$'\\50\\101'")
        self.assertEqual(encode_outer_word(b"(1"), "$'\\0501'")

    def test_every_synthesized_arithmetic_value(self) -> None:
        source = "printf '%s\\n' " + " ".join(
            _arithmetic_expansion(value) for value in range(1, 1000)
        )
        result = subprocess.run(
            [BASH, "--noprofile", "--norc", "-c", source],
            capture_output=True,
            check=False,
        )
        expected = "".join("%d\n" % value for value in range(1, 1000)).encode()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, expected)
        self.assertEqual(result.stderr, b"")

    def test_checked_in_examples_match_the_encoder(self) -> None:
        for stem in ("echo-works", "primes-under-100"):
            source = (ROOT / "examples" / (stem + ".sh")).read_bytes()
            checked_in = (ROOT / "examples" / (stem + ".bf")).read_text(
                encoding="ascii"
            )
            self.assertEqual(checked_in, encode_program(source))


if __name__ == "__main__":
    unittest.main()

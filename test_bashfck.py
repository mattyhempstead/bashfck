#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

from bashfck import CHARSET, encode_program


BASH = os.environ.get("BASH_PATH", "bash")
ROOT = Path(__file__).resolve().parent


def run_encoded(program: bytes) -> subprocess.CompletedProcess[bytes]:
    encoded = encode_program(program)
    return subprocess.run(
        [BASH, "--noprofile", "--norc", "-c", encoded],
        capture_output=True,
        check=False,
    )


class BashfckTests(unittest.TestCase):
    def test_echo_works(self) -> None:
        encoded = encode_program(b"echo works")
        self.assertLessEqual(set(encoded), CHARSET)

        result = run_encoded(b"echo works")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"works\n")
        self.assertEqual(result.stderr, b"")

    def test_exit_status(self) -> None:
        result = run_encoded(b"exit 23")
        self.assertEqual(result.returncode, 23)

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
        encoded = encode_program(b": <<'BASHFCK'\n" + data + b"\nBASHFCK\n:")
        self.assertLessEqual(set(encoded), CHARSET)


if __name__ == "__main__":
    unittest.main()

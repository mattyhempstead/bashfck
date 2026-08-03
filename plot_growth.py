#!/usr/bin/env python3
"""Plot Bash source size against seven-character bashfck output size.

Install the plotting dependency first:

    python3 -m pip install matplotlib

Then run:

    python3 plot_growth.py

The script writes ``output-size.png`` by default.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence

from bashfck import encode_program


def built_in_programs(repo_root: Path) -> list[tuple[str, bytes]]:
    """Return a curated corpus of distinct, realistic Bash programs."""
    examples = repo_root / "examples"

    return [
        ("no-op", b":\n"),
        ("hello world", b"echo 'Hello, World!'\n"),
        ("formatted output", b"printf 'user=%s id=%04d\\n' \"alice\" 42\n"),
        ("variables", b"name=world\ngreeting=\"Hello, $name\"\nprintf '%s\\n' \"$greeting\"\n"),
        ("arithmetic", b"width=12\nheight=7\narea=$((width * height))\necho \"$area\"\n"),
        ("word loop", b"for color in red green blue; do printf '<%s>\\n' \"$color\"; done\n"),
        ("c-style loop", b"for ((i = 0; i < 10; i++)); do printf '%d ' \"$i\"; done\necho\n"),
        ("while countdown", b"n=5\nwhile ((n > 0)); do echo \"$n\"; ((n--)); done\necho lift-off\n"),
        ("until ready", b"attempt=0\nuntil ((attempt == 3)); do ((attempt++)); sleep 1; done\n"),
        (
            "conditional",
            b"score=87\nif ((score >= 90)); then grade=A\nelif ((score >= 80)); "
            b"then grade=B\nelse grade=C\nfi\necho \"$grade\"\n",
        ),
        (
            "case statement",
            b"case ${1:-start} in\n  start) echo starting ;;\n  stop) echo stopping "
            b";;\n  *) echo 'usage: start|stop' >&2; exit 2 ;;\nesac\n",
        ),
        (
            "function",
            b"greet() {\n  local person=${1:-stranger}\n  printf 'Welcome, %s!\\n' "
            b"\"$person\"\n}\ngreet \"Ada\"\n",
        ),
        (
            "recursive factorial",
            b"factorial() {\n  if (( $1 <= 1 )); then echo 1\n  else local previous"
            b"\n    previous=$(factorial $(($1 - 1)))\n    echo $(($1 * previous))"
            b"\n  fi\n}\nfactorial 6\n",
        ),
        ("indexed array", b"cities=(London Tokyo Nairobi)\ncities+=(Lima)\nprintf '%s\\n' \"${cities[@]}\"\n"),
        (
            "arguments",
            b"if (($# == 0)); then echo \"usage: $0 FILE...\" >&2; exit 64; fi\n"
            b"for path; do printf '%s\\n' \"$path\"; done\n",
        ),
        (
            "getopts",
            b"verbose=false\noutput=/dev/stdout\nwhile getopts 'vo:' option; do\n  "
            b"case $option in v) verbose=true ;; o) output=$OPTARG ;; *) exit 2 ;; "
            b"esac\ndone\n$verbose && echo verbose >\"$output\"\n",
        ),
        (
            "line reader",
            b"while IFS= read -r line || [[ -n $line ]]; do\n  printf '%6d  %s\\n' "
            b"\"${#line}\" \"$line\"\ndone < \"${1:-/dev/stdin}\"\n",
        ),
        (
            "csv parser",
            b"while IFS=, read -r name email role; do\n  [[ $name == name ]] && "
            b"continue\n  printf '%s <%s> [%s]\\n' \"$name\" \"$email\" \"$role\"\n"
            b"done < users.csv\n",
        ),
        (
            "pipeline",
            b"printf '%s\\n' banana apple cherry apricot | sort | uniq | "
            b"awk '/^a/ { print toupper($0) }'\n",
        ),
        ("command substitution", b"kernel=$(uname -s)\nrelease=$(uname -r)\necho \"$kernel $release\"\n"),
        (
            "process substitution",
            b"diff -u <(printf '%s\\n' alpha beta gamma) "
            b"<(printf '%s\\n' alpha beta delta)\n",
        ),
        (
            "here document",
            b"cat <<'MESSAGE'\nThis text is passed through standard input.\n"
            b"Variables such as $HOME remain literal.\nMESSAGE\n",
        ),
        ("here string", b"read -r first rest <<<\"one two three\"\nprintf 'first=%s rest=%s\\n' \"$first\" \"$rest\"\n"),
        ("brace expansion", b"mkdir -p project/{src,test,docs}/{unit,integration}\nprintf '%s\\n' file{01..12}.log\n"),
        (
            "glob loop",
            b"shopt -s nullglob\nfor image in ./*.{png,jpg,gif}; do\n  printf '%s\\n' "
            b"\"${image##*/}\"\ndone\n",
        ),
        ("subshell", b"original=$PWD\n(cd /tmp && printf 'inside: %s\\n' \"$PWD\")\nprintf 'outside: %s\\n' \"$original\"\n"),
        (
            "command group",
            b"{ date -u '+started=%FT%TZ'; printf 'pid=%d\\n' \"$$\"; uname -a; } "
            b">run-metadata.txt\n",
        ),
        (
            "file checks",
            b"path=${1:-config.ini}\n[[ -e $path ]] || { echo \"missing: $path\" >&2; "
            b"exit 1; }\n[[ -r $path && -s $path ]] && echo ready\n",
        ),
        (
            "regex validation",
            b"value=${1:-}\nif [[ $value =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; "
            b"then echo valid; else echo invalid; fi\n",
        ),
        (
            "parameter defaults",
            b": \"${HOST:=localhost}\"\n: \"${PORT:=8080}\"\nurl=\"http://${HOST}:${PORT}"
            b"${BASE_PATH:-/api}\"\necho \"$url\"\n",
        ),
        (
            "path manipulation",
            b"path=/var/archive/report.final.csv\nfile=${path##*/}\nextension=${file##*.}"
            b"\nstem=${file%.*}\nprintf '%s (%s)\\n' \"$stem\" \"$extension\"\n",
        ),
        ("string replacement", b"template='Hello, NAME. Welcome to PLACE.'\nmessage=${template/NAME/Ada}\nmessage=${message/PLACE/London}\necho \"$message\"\n"),
        (
            "cleanup trap",
            b"temporary=$(mktemp -d)\ncleanup() { rm -rf \"$temporary\"; }\ntrap cleanup "
            b"EXIT HUP INT TERM\nprintf 'working in %s\\n' \"$temporary\"\n",
        ),
        (
            "parallel jobs",
            b"pids=()\nfor delay in 1 2 3; do (sleep \"$delay\"; echo \"finished "
            b"$delay\") & pids+=(\"$!\"); done\nfor pid in \"${pids[@]}\"; do wait "
            b"\"$pid\"; done\n",
        ),
        (
            "select menu",
            b"PS3='Choose an action: '\nselect action in build test deploy quit; do\n"
            b"  [[ $action == quit ]] && break\n  [[ -n $action ]] && echo "
            b"\"running $action\" && break\ndone\n",
        ),
        ("random identifier", b"printf -v identifier '%08x-%04x-%04x' \"$RANDOM\" \"$RANDOM\" \"$RANDOM\"\necho \"$identifier\"\n"),
        (
            "directory walk",
            b"root=${1:-.}\nwhile IFS= read -r -d '' path; do\n  printf '%10d %s\\n' "
            b"\"$(wc -c <\"$path\")\" \"$path\"\ndone < <(find \"$root\" -type f "
            b"-print0)\n",
        ),
        (
            "disk summary",
            b"df -Pk | awk 'NR > 1 { used += $3; available += $4 } END { printf "
            b"\"used=%dKB available=%dKB\\n\", used, available }'\n",
        ),
        (
            "fibonacci",
            b"a=0\nb=1\nfor ((i = 0; i < 15; i++)); do\n  printf '%d\\n' \"$a\"\n  "
            b"next=$((a + b))\n  a=$b\n  b=$next\ndone\n",
        ),
        (
            "greatest common divisor",
            b"a=${1:-1071}\nb=${2:-462}\nwhile ((b != 0)); do\n  remainder=$((a % b))"
            b"\n  a=$b\n  b=$remainder\ndone\nprintf '%d\\n' \"$a\"\n",
        ),
        (
            "multiplication table",
            b"for row in {1..12}; do\n  for column in {1..12}; do\n    printf "
            b"'%4d' \"$((row * column))\"\n  done\n  printf '\\n'\ndone\n",
        ),
        ("echo works", (examples / "echo-works.sh").read_bytes()),
        ("primes < 100", (examples / "primes-under-100.sh").read_bytes()),
    ]


def linear_trend(
    input_sizes: list[int],
    output_sizes: list[int],
) -> tuple[list[int], list[float], float]:
    """Return endpoints for the least-squares linear trend."""
    input_mean = sum(input_sizes) / len(input_sizes)
    output_mean = sum(output_sizes) / len(output_sizes)
    input_variance = sum((size - input_mean) ** 2 for size in input_sizes)
    covariance = sum(
        (input_size - input_mean) * (output_size - output_mean)
        for input_size, output_size in zip(input_sizes, output_sizes)
    )
    slope = covariance / input_variance
    intercept = output_mean - slope * input_mean
    endpoints = [min(input_sizes), max(input_sizes)]
    return endpoints, [slope * size + intercept for size in endpoints], slope


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="plot bashfck output size for representative Bash programs"
    )
    parser.add_argument(
        "-o",
        "--output",
        default="output-size.png",
        help="image path to write",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    try:
        import matplotlib.pyplot as plt
    except ImportError as error:
        raise SystemExit(
            "matplotlib is required: python3 -m pip install matplotlib"
        ) from error

    repo_root = Path(__file__).resolve().parent

    sample_programs = built_in_programs(repo_root)
    sample_input_sizes = [len(program) for _, program in sample_programs]
    sample_output_sizes = [
        len(encode_program(program))
        for _, program in sample_programs
    ]

    trend_input_sizes, trend_output_sizes, trend_coefficient = linear_trend(
        sample_input_sizes,
        sample_output_sizes,
    )

    figure, axis = plt.subplots(figsize=(10, 6))
    axis.scatter(
        sample_input_sizes,
        sample_output_sizes,
        s=28,
        alpha=0.7,
        label="curated Bash programs",
    )
    axis.plot(
        trend_input_sizes,
        trend_output_sizes,
        color="tab:orange",
        linewidth=2,
        label=f"linear trend (coefficient: {trend_coefficient:.2f})",
    )

    axis.set_title("bashfck output growth")
    axis.set_xlabel("input Bash source (bytes)")
    axis.set_ylabel("encoded program (characters)")
    axis.grid(True)
    axis.legend()
    figure.tight_layout()
    figure.savefig(args.output, dpi=200)

    print("program,input_bytes,output_characters,expansion_ratio")
    for (name, _), input_size, output_size in zip(
        sample_programs,
        sample_input_sizes,
        sample_output_sizes,
    ):
        ratio = output_size / input_size if input_size else 0.0
        print("%s,%d,%d,%.2f" % (name, input_size, output_size, ratio))

    print("wrote %s" % args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

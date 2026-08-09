# bashfck research notes

This document contains the work that is useful for understanding the search,
but is not required to understand the seven-character core method.

The primary README intentionally focuses on the current result. This file
records the assumptions, earlier alphabets, failed reductions, semantic
trade-offs, and possible future directions.

## Search contract

Character-count claims depend strongly on what is allowed.

The main result uses this contract:

- the output is Bash source;
- the output is self-contained;
- no external utilities are required;
- no preloaded aliases or functions are required;
- no specially prepared environment variables are required;
- no filesystem contents are assumed;
- unquoted `$0` may be used when it expands to one command word resolving to
  the running Bash executable;
- nested Bash startup state is assumed not to intercept the bootstrap;
- NUL bytes are excluded;
- ordinary stdin does not need to survive the bootstrap.

Changing any of these assumptions can produce a smaller or more convenient
program, but it is a different result.

## Progression

| Stage | Alphabet | Size | Execution model | Important cost |
|---|---|---:|---|---|
| Direct octal | ` $'\01234567` | 12 | current-shell `eval` | compact, but uses every octal digit |
| Base-seven | ` $'\0123456` | 11 | `printf -v` decoder | substantially larger |
| `%q` decoder | ` $'\012456` | 10 | generated quoting fragments | decoder is complex |
| Current-shell | ` $'\01456` | 9 | construct `eval` | modifies current shell |
| Direct child Bash | ` $'\015c` | 8 | `$0 -c ...` | requires a separator and `c` |
| Generated `-c` stage | `$'\<015` | 7 | two `$0<<<...` re-entries, then `$0 -c` | consumes stdin |
| Launcher-assisted | ` $'\015` | 7 | launcher sets `$0=eval` | not directly self-contained |

All of these constructions are linear in input size. Alphabet reduction and
output-size reduction are separate optimization problems.

## Twelve characters: direct ANSI-C octal

The baseline is straightforward:

```bash
eval -- $'\145\143\150\157\040\167\157\162\153\163'
```

The payload alphabet consists of:

- a separator;
- `$`, single quote, and backslash;
- octal digits `0` through `7`.

This approach has low overhead: each source byte becomes one four-character
octal escape plus a fixed wrapper.

It establishes the basic principle but does not exploit Bash's parser or
arithmetic system.

## Eleven characters: remove octal digit 7

The first reduction omitted literal `7`.

Bytes whose octal spellings contain `7` were handled by a second-stage decoder
using Bash's builtin `printf -v` and arithmetic expansion. This retained a
self-contained current-shell execution model but increased output size
significantly.

The important lesson was that the octal alphabet does not have to be complete
if the decoder can construct the missing numerals.

## Ten characters: omit octal digits 3 and 7

A better digit subset was found by searching for a set that could still spell
the required decoder builtins.

Bash's `printf %q`, combined with precision, can manufacture fragments of shell
quoting syntax at runtime. That allowed both `3` and `7` to disappear from the
outer alphabet.

This result was smaller in alphabet size but relied on a more intricate
bootstrap. It also demonstrated that generated shell syntax can be assembled
from builtin output, not only from direct octal escapes.

## Nine characters: construct `eval` directly

The nine-character result used a restricted digit set and arithmetic expansion
to construct the octal numerals required to spell `eval` and the payload.

It executed in the current shell, which means assignments and function
definitions could remain visible after execution. That is sometimes useful,
but it is a different semantic contract from the child-Bash results.

This stage also retained a literal separator.

## Eight characters: replace `eval` with `$0 -c`

The next reduction stopped spelling an evaluator builtin.

When the payload is pasted into a normal Bash or passed through `bash -c`, `$0`
usually identifies an executable Bash. It can therefore launch a new parser:

```bash
$0 -c 'NEXT_STAGE'
```

The outer alphabet needs:

```text
space $ ' \ 0 1 5 c
```

This version preserves normal stdin for the original program because the
program is supplied as the `-c` argument.

The cost is child-process execution and dependence on `$0`.

## Seven characters: bootstrap `-c` through here-strings

The decisive reduction was:

```bash
$0<<<$'NEXT_STAGE'
```

This removes both the literal `c` and the separator required by a direct outer
`$0 -c` command.

The new `<` character costs one alphabet slot, producing a net reduction from
eight to seven.

The current encoder uses two such parser re-entries. The generated second stage
is equivalent to:

```text
$0<TAB>$'-\143'<TAB>$'ORIGINAL_BYTES'
```

The tab separators and the octal digits spelling `c` are constructed at an
intermediate level, so they do not enlarge the outer alphabet. The final Bash
receives the original bytes as its `-c` command string.

An earlier seven-character implementation used a third here-string followed by
`builtin eval --`. It was correct under the stated clean-environment contract,
but substantially larger. It also protected against a function named `eval`
without protecting against a function named `builtin` itself.

This version is directly pasteable, but the first nested Bash already reads its
source from stdin. The original program therefore receives EOF even though its
own source is ultimately supplied with `-c`.

## Output-length reductions within the seven-character alphabet

The alphabet-size result and the output-length result are separate. The current
encoder shortens the same seven-character construction in several ways:

- ANSI-C octal escapes use one to three digits rather than always using three;
- decoder-safe payload bytes remain literal;
- leading-zero arithmetic constants exploit Bash's octal interpretation;
- one arithmetic expansion can generate up to three adjacent decimal digits;
- the decoder uses backslash-quoted word fragments instead of wrapping every
  literal run in another ANSI-C word.

Examples of the arithmetic spellings are:

```text
2 -> $((1<<1))
3 -> $((010-5))
6 -> $((11-5))
7 -> $((010-1))
143 -> $((151-010))
```

These changes reduced the 20-byte README example from 5,555 encoded characters
to 511 without changing the seven-character alphabet or the execution contract.

## Seven characters with a launcher

A separate seven-character construction can preserve stdin when a launcher
controls `$0`, for example by arranging for `$0` to expand to `eval`.

That alphabet replaces `<` with a separator:

```text
space $ ' \ 0 1 5
```

It is useful as a comparison but is not the core result because the launcher
imports execution state that is outside the counted payload.

## Six-character search

No six-character Bash-only construction has been found under the core
direct-paste contract. This is not a proof over the entire Bash grammar.

### Fixed cost of the here-string architecture

The recursive source-reader architecture needs five characters before payload
data contributes anything:

```text
$ 0 < ' \
```

A six-character construction gets only one additional source character.

A fixed-point search over printable sixth characters examined which bytes could
be generated through repeated ANSI-C quoting and parser re-entry.

The strongest candidates were:

| Extra character | Reachable printable bytes | Main blocker |
|---|---|---|
| `5` | includes `$'(-05<@E\hm` | reaches `(` and `-`, but not `)` |
| `1` | adds controls including tab/newline | gains separators, but no evaluator or byte bridge |
| `4` | reaches a literal space | still lacks an evaluator and closing syntax |
| `.` | reaches the `.` builtin | no source filename or generated source channel |

No tested candidate reached both sides of a useful paired syntax construct such
as `$(...)`, `$((...))`, `${...}`, `[...]`, or `{...}`.

### Other routes checked

The search also considered:

- deriving `c` from `$-`;
- separators created by tabs or newlines;
- redirections as token separators;
- brace expansion;
- positional and special parameters;
- the single-character builtins `.` and `:`;
- parser re-entry through `exec`, `trap`, `fc`, and command substitution;
- process substitution;
- builtin output from `set`, `help`, `alias`, and `trap`;
- arithmetic and array-subscript side effects;
- shell history;
- specially chosen `$0` values;
- external utilities.

Each successful-looking route either needed a seventh source character or
imported state excluded by the core contract.

## Assumption-dependent reductions

Results below seven are much easier when outside state is permitted.

Examples include:

- a preloaded one-character function that evaluates its argument;
- an alias installed before the payload is parsed;
- a prepared environment variable containing a decoder;
- a specially chosen `$0`;
- a known readable file containing Bash source;
- shell history containing useful text;
- an external interpreter or byte-construction utility.

These are valid code-golf variants, but they should be labelled separately
because part of the decoder is no longer counted.

## POSIX `sh` detour

A portable `sh` version was explored before the project returned to Bash.

Traditional POSIX `sh` can reconstruct arbitrary non-NUL source with `printf`,
command substitution, and `eval`, but the alphabet is larger. POSIX.1-2024 adds
dollar-single-quoted strings, which reduces the gap, though installed-shell
support is not universal.

The Bash result is more compelling for this project because Bash-specific
ANSI-C quoting, arithmetic expansion, here-strings, and `$0` parser re-entry
interact directly to reduce the alphabet.

## Compatibility notes

The seven-character construction uses:

- ANSI-C quoted strings;
- arithmetic expansion;
- here-strings;
- Bash's `-c` invocation option.

These are longstanding Bash features. Nevertheless, repository CI should test:

- current Bash on Linux;
- macOS system `/bin/bash` 3.2;
- Bash invoked with clean startup files;
- syntax and behavior under unusual environment values where relevant.

Do not infer Bash 3.2 compatibility from a modern Bash compatibility mode alone;
an actual Bash 3.2 process is the stronger test.

## Semantic comparison

| Property | 7-char generated `-c` | 8-char direct `$0 -c` | 9-char current-shell |
|---|---|---|---|
| Directly pasteable | yes | yes | yes |
| Uses child Bash | yes | yes | no |
| Preserves stdin | no | yes | yes |
| Preserves parent variables/functions | no | no | yes |
| Depends on executable `$0` | yes | yes | no |
| Smallest alphabet | yes | no | no |

## Future work

The most useful next investigations are:

1. Search parser states beyond the recursive here-string architecture.
2. Model quote removal and parser re-entry formally rather than only as byte
   reachability.
3. Search for a six-character pair that constructs both sides of a delimiter.
4. Prove or improve the bounded arithmetic synthesis used for output length.
5. Separate minimum alphabet size from minimum output length for each alphabet.
6. Add real cross-version CI results and benchmark data.
7. Record reproducible search programs and machine-readable result files.

A six-character result should be treated as unverified until it executes
arbitrary non-NUL Bash source under a clearly stated, reproducible contract.

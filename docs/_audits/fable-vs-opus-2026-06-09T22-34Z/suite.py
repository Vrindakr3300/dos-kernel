"""Fable 5 vs Opus 4.8 head-to-head — the task suite.

Two benchmark families, each a HONEST PROXY for a published suite the official
harness of which is too heavy to stand up here (SWE-bench Verified needs a Docker
image per instance; Terminal-Bench needs its own task containers). We say so in
the artifact and we name them `swe_proxy` / `term_proxy`, never the leaderboard
name, so nobody mistakes these for the official 95.0% / 84.3% numbers.

The DESIGN borrows the one thing that makes those suites trustworthy and reuses
the exact pattern this repo's own `benchmark/fleet_horizon/forge.py` uses: a
**hidden, OS-recorded oracle**. The agent is shown a task and a buggy/empty repo;
it never sees the grading test. After it commits, we materialize a CLEAN checkout
of *its* HEAD (`git archive HEAD | tar -x`, so a dirtied working tree cannot fake
a pass) and run the hidden oracle there. The oracle's EXIT CODE is the witness —
the agent authored zero bytes of it. That is the same non-forgeable-witness
philosophy DOS is built on (docs/121 acceptance verb): pass/fail is a property of
the world (the OS ran the code), not of the agent's narration.

Each task is `Task(key, family, prompt, setup, oracle_files, oracle_cmd)`:
  * `prompt`       — the literal task string handed to `claude -p`.
  * `setup(repo)`  — seed the throwaway git repo (buggy source, fixtures, a plan).
                     Does NOT write the oracle test. Leaves an initial commit.
  * `oracle_files` — {relpath: content} written into the CLEAN checkout *after*
                     export, before grading (the hidden tests the agent never saw).
  * `oracle_cmd`   — the command whose exit code is the pass/fail witness.

`family` is "swe" (a bug-fix / feature with a hidden pytest oracle, the
SWE-bench-Verified shape) or "term" (a shell/file/tool task with a hidden
command-output oracle, the Terminal-Bench shape).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Task:
    key: str
    family: str                       # "swe" | "term"
    prompt: str
    setup: Callable[[Path], None]
    oracle_files: dict[str, str]      # hidden grading files (relpath -> content)
    oracle_cmd: str                   # exit-code-is-witness grading command
    note: str = ""                    # what capability this probes


# ---------------------------------------------------------------------------
# helpers shared by setups
# ---------------------------------------------------------------------------

def _w(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ===========================================================================
# FAMILY A — SWE-bench-Verified-shaped: a real bug, a hidden pytest oracle.
# Each repo ships WORKING-LOOKING but SUBTLY BROKEN code + a couple of passing
# "sanity" tests the agent CAN see; the HIDDEN oracle asserts the actual fix.
# ===========================================================================

# --- swe1: off-by-one in a date-range generator -------------------------------
def _setup_swe1(repo: Path) -> None:
    _w(repo, "daterange.py",
       "from datetime import date, timedelta\n\n"
       "def days_between(start, end):\n"
       "    \"\"\"Return the list of date objects from start to end INCLUSIVE.\"\"\"\n"
       "    out = []\n"
       "    d = start\n"
       "    while d < end:            # BUG: excludes the end date\n"
       "        out.append(d)\n"
       "        d += timedelta(days=1)\n"
       "    return out\n")
    _w(repo, "tests/test_sanity.py",
       "from daterange import days_between\n"
       "from datetime import date\n"
       "def test_len_nonneg():\n"
       "    assert days_between(date(2020,1,1), date(2020,1,3))\n")

_ORACLE_SWE1 = (
    "from daterange import days_between\n"
    "from datetime import date\n"
    "def test_inclusive():\n"
    "    r = days_between(date(2020,1,1), date(2020,1,3))\n"
    "    assert r[0] == date(2020,1,1)\n"
    "    assert r[-1] == date(2020,1,3)   # end must be included\n"
    "    assert len(r) == 3\n"
    "def test_single_day():\n"
    "    assert days_between(date(2020,5,5), date(2020,5,5)) == [date(2020,5,5)]\n"
)

# --- swe2: incorrect cache eviction (LRU keeps the WRONG key) ------------------
def _setup_swe2(repo: Path) -> None:
    _w(repo, "lru.py",
       "class LRUCache:\n"
       "    def __init__(self, cap):\n"
       "        self.cap = cap\n"
       "        self.d = {}\n"
       "    def get(self, k):\n"
       "        return self.d.get(k)\n"
       "    def put(self, k, v):\n"
       "        self.d[k] = v\n"
       "        if len(self.d) > self.cap:\n"
       "            # BUG: pops an arbitrary key, not the least-recently-used\n"
       "            self.d.pop(next(iter(self.d)))\n")
    _w(repo, "tests/test_sanity.py",
       "from lru import LRUCache\n"
       "def test_put_get():\n"
       "    c = LRUCache(2); c.put('a',1); assert c.get('a') == 1\n")

_ORACLE_SWE2 = (
    "from lru import LRUCache\n"
    "def test_evicts_lru():\n"
    "    c = LRUCache(2)\n"
    "    c.put('a', 1); c.put('b', 2)\n"
    "    assert c.get('a') == 1          # touch 'a' -> 'b' is now LRU\n"
    "    c.put('c', 3)                   # must evict 'b', keep 'a' and 'c'\n"
    "    assert c.get('b') is None\n"
    "    assert c.get('a') == 1\n"
    "    assert c.get('c') == 3\n"
)

# --- swe3: integer overflow / wrong rounding in a money splitter ---------------
def _setup_swe3(repo: Path) -> None:
    _w(repo, "split.py",
       "def split_bill(total_cents, n):\n"
       "    \"\"\"Split total_cents among n people. Everyone pays a whole number of\n"
       "    cents; the sum of shares MUST equal total_cents exactly (remainder\n"
       "    distributed one cent at a time to the first people).\"\"\"\n"
       "    base = total_cents // n\n"
       "    return [base] * n           # BUG: drops the remainder cents\n")
    _w(repo, "tests/test_sanity.py",
       "from split import split_bill\n"
       "def test_even():\n"
       "    assert split_bill(100, 4) == [25,25,25,25]\n")

_ORACLE_SWE3 = (
    "from split import split_bill\n"
    "def test_remainder_distributed():\n"
    "    s = split_bill(100, 3)\n"
    "    assert sum(s) == 100            # nothing lost\n"
    "    assert sorted(s) == [33, 33, 34]\n"
    "def test_more_remainder():\n"
    "    s = split_bill(103, 4)\n"
    "    assert sum(s) == 103\n"
    "    assert max(s) - min(s) <= 1     # spread fairly\n"
)

# --- swe4: regex bug — email validator accepts/rejects wrong ------------------
def _setup_swe4(repo: Path) -> None:
    _w(repo, "validate.py",
       "import re\n"
       "def is_valid_email(s):\n"
       "    # BUG: '.' unescaped matches any char; no anchor -> substrings pass\n"
       "    return bool(re.match(r'[a-z]+@[a-z]+.[a-z]+', s))\n")
    _w(repo, "tests/test_sanity.py",
       "from validate import is_valid_email\n"
       "def test_basic():\n"
       "    assert is_valid_email('a@b.co')\n")

_ORACLE_SWE4 = (
    "from validate import is_valid_email\n"
    "def test_rejects_bad():\n"
    "    assert not is_valid_email('a@bxco')      # no dot -> must reject\n"
    "    assert not is_valid_email('a@b.co extra')# trailing junk -> reject\n"
    "    assert not is_valid_email('no-at-sign')\n"
    "def test_accepts_good():\n"
    "    assert is_valid_email('user@host.com')\n"
)

# --- swe5: a stateful bug — counter not thread-safe-shaped reset --------------
def _setup_swe5(repo: Path) -> None:
    _w(repo, "counter.py",
       "class Counter:\n"
       "    instances = []              # BUG: shared mutable class attr\n"
       "    def __init__(self):\n"
       "        self.n = 0\n"
       "    def bump(self):\n"
       "        self.n += 1\n"
       "        self.instances.append(self.n)\n")
    _w(repo, "tests/test_sanity.py",
       "from counter import Counter\n"
       "def test_bump():\n"
       "    c = Counter(); c.bump(); assert c.n == 1\n")

_ORACLE_SWE5 = (
    "from counter import Counter\n"
    "def test_instances_not_shared():\n"
    "    a = Counter(); b = Counter()\n"
    "    a.bump(); a.bump()\n"
    "    b.bump()\n"
    "    # each instance must track only its OWN bumps\n"
    "    assert a.instances == [1, 2]\n"
    "    assert b.instances == [1]\n"
)

# --- swe6: implement a missing feature from a spec (not just fix) -------------
def _setup_swe6(repo: Path) -> None:
    _w(repo, "roman.py",
       "def to_roman(n):\n"
       "    raise NotImplementedError   # implement me per the docstring spec\n"
       "# Spec: convert an int 1..3999 to a Roman numeral string.\n"
       "# 4 -> 'IV', 9 -> 'IX', 40 -> 'XL', 1994 -> 'MCMXCIV'.\n")
    _w(repo, "tests/test_sanity.py",
       "from roman import to_roman\n"
       "def test_one():\n"
       "    assert to_roman(1) == 'I'\n")

_ORACLE_SWE6 = (
    "from roman import to_roman\n"
    "def test_subtractive():\n"
    "    assert to_roman(4) == 'IV'\n"
    "    assert to_roman(9) == 'IX'\n"
    "    assert to_roman(40) == 'XL'\n"
    "    assert to_roman(1994) == 'MCMXCIV'\n"
    "    assert to_roman(3888) == 'MMMDCCCLXXXVIII'\n"
)

# --- swe7: fix a crash on edge input (empty / None handling) ------------------
def _setup_swe7(repo: Path) -> None:
    _w(repo, "stats.py",
       "def median(xs):\n"
       "    xs = sorted(xs)\n"
       "    n = len(xs)\n"
       "    return xs[n // 2]           # BUG: wrong for even n; crashes on []\n")
    _w(repo, "tests/test_sanity.py",
       "from stats import median\n"
       "def test_odd():\n"
       "    assert median([3,1,2]) == 2\n")

_ORACLE_SWE7 = (
    "import pytest\n"
    "from stats import median\n"
    "def test_even():\n"
    "    assert median([1,2,3,4]) == 2.5    # mean of the two middle\n"
    "def test_empty_raises():\n"
    "    with pytest.raises((ValueError, IndexError)):\n"
    "        median([])\n"
)

# --- swe8: a bug across TWO files (import + logic) ----------------------------
def _setup_swe8(repo: Path) -> None:
    _w(repo, "geom/__init__.py", "")
    _w(repo, "geom/shapes.py",
       "import math\n"
       "def circle_area(r):\n"
       "    return math.pi * r          # BUG: forgot to square r\n")
    _w(repo, "geom/calc.py",
       "from geom.shapes import circle_area\n"
       "def total_area(radii):\n"
       "    return sum(circle_area(r) for r in radii)\n")
    _w(repo, "tests/test_sanity.py",
       "from geom.calc import total_area\n"
       "def test_runs():\n"
       "    assert total_area([1]) > 0\n")

_ORACLE_SWE8 = (
    "import math\n"
    "from geom.shapes import circle_area\n"
    "from geom.calc import total_area\n"
    "def test_area():\n"
    "    assert abs(circle_area(2) - math.pi*4) < 1e-9\n"
    "    assert abs(total_area([1,2]) - (math.pi + math.pi*4)) < 1e-9\n"
)

# --- swe9: parsing bug — CSV with quoted commas --------------------------------
def _setup_swe9(repo: Path) -> None:
    _w(repo, "csvparse.py",
       "def parse_line(line):\n"
       "    # BUG: naive split breaks on quoted fields containing commas\n"
       "    return line.split(',')\n")
    _w(repo, "tests/test_sanity.py",
       "from csvparse import parse_line\n"
       "def test_plain():\n"
       "    assert parse_line('a,b,c') == ['a','b','c']\n")

_ORACLE_SWE9 = (
    "from csvparse import parse_line\n"
    "def test_quoted_comma():\n"
    "    assert parse_line('a,\"b,c\",d') == ['a', 'b,c', 'd']\n"
    "def test_plain_still_works():\n"
    "    assert parse_line('x,y,z') == ['x','y','z']\n"
)

# --- swe10: recursion depth / iterative rewrite -------------------------------
def _setup_swe10(repo: Path) -> None:
    _w(repo, "flatten.py",
       "def flatten(xs):\n"
       "    out = []\n"
       "    for x in xs:\n"
       "        if isinstance(x, list):\n"
       "            out.append(flatten(x))   # BUG: appends nested list, not extends\n"
       "        else:\n"
       "            out.append(x)\n"
       "    return out\n")
    _w(repo, "tests/test_sanity.py",
       "from flatten import flatten\n"
       "def test_flat():\n"
       "    assert flatten([1,2,3]) == [1,2,3]\n")

_ORACLE_SWE10 = (
    "from flatten import flatten\n"
    "def test_nested():\n"
    "    assert flatten([1,[2,[3,4]],5]) == [1,2,3,4,5]\n"
    "    assert flatten([[1],[2],[3]]) == [1,2,3]\n"
    "    assert flatten([]) == []\n"
)

# --- swe11: timezone / arithmetic bug -----------------------------------------
def _setup_swe11(repo: Path) -> None:
    _w(repo, "duration.py",
       "def humanize(seconds):\n"
       "    \"\"\"Return 'Hh Mm Ss' dropping leading zero units. 3661 -> '1h 1m 1s'.\n"
       "    61 -> '1m 1s'. 5 -> '5s'.\"\"\"\n"
       "    h = seconds // 3600\n"
       "    m = seconds // 60           # BUG: should be (seconds % 3600)//60\n"
       "    s = seconds % 60\n"
       "    return f'{h}h {m}m {s}s'\n")
    _w(repo, "tests/test_sanity.py",
       "from duration import humanize\n"
       "def test_runs():\n"
       "    assert isinstance(humanize(5), str)\n")

_ORACLE_SWE11 = (
    "from duration import humanize\n"
    "def test_values():\n"
    "    assert humanize(3661) == '1h 1m 1s'\n"
    "    assert humanize(61) == '1m 1s'\n"
    "    assert humanize(5) == '5s'\n"
    "    assert humanize(7325) == '2h 2m 5s'\n"
)

# --- swe12: a logic bug in a small state machine ------------------------------
def _setup_swe12(repo: Path) -> None:
    _w(repo, "brackets.py",
       "def balanced(s):\n"
       "    stack = []\n"
       "    pairs = {')':'(', ']':'[', '}':'{'}\n"
       "    for ch in s:\n"
       "        if ch in '([{':\n"
       "            stack.append(ch)\n"
       "        elif ch in pairs:\n"
       "            if not stack:\n"
       "                return False\n"
       "            stack.pop()         # BUG: doesn't check it MATCHES\n"
       "    return not stack\n")
    _w(repo, "tests/test_sanity.py",
       "from brackets import balanced\n"
       "def test_simple():\n"
       "    assert balanced('()')\n")

_ORACLE_SWE12 = (
    "from brackets import balanced\n"
    "def test_mismatch():\n"
    "    assert not balanced('(]')       # wrong closer\n"
    "    assert not balanced('([)]')     # interleaved\n"
    "    assert balanced('([]{})')\n"
    "    assert not balanced('(((')\n"
)

# Common pytest oracle command (quiet, no cache, the hidden test only).
_PYTEST = "python -m pytest -q -p no:cacheprovider tests/test_oracle.py"


# ===========================================================================
# FAMILY B — Terminal-Bench-shaped: a shell/file/tool task, hidden cmd oracle.
# These need the agent to actually manipulate the filesystem / produce an
# artifact a deterministic command then checks. The grader is a python script
# the agent never sees, run against the clean checkout.
# ===========================================================================

# --- term1: produce a file with exact content ---------------------------------
def _setup_term1(repo: Path) -> None:
    _w(repo, "README.md", "Task repo. See instructions.\n")

_ORACLE_TERM1 = (
    "import os\n"
    "def test_fizzbuzz_output():\n"
    "    assert os.path.exists('out.txt'), 'out.txt missing'\n"
    "    lines = open('out.txt').read().splitlines()\n"
    "    assert len(lines) == 15, f'expected 15 lines, got {len(lines)}'\n"
    "    assert lines[0] == '1'\n"
    "    assert lines[2] == 'Fizz'\n"
    "    assert lines[4] == 'Buzz'\n"
    "    assert lines[14] == 'FizzBuzz'\n"
)

# --- term2: write + make a script executable that prints a value --------------
def _setup_term2(repo: Path) -> None:
    _w(repo, "data.txt", "3\n7\n2\n9\n4\n")

_ORACLE_TERM2 = (
    "import subprocess, os\n"
    "def test_sum_script():\n"
    "    assert os.path.exists('sum.py'), 'sum.py missing'\n"
    "    r = subprocess.run(['python','sum.py'], capture_output=True, text=True)\n"
    "    assert r.stdout.strip() == '25', f'got {r.stdout!r}'\n"
)

# --- term3: refactor a JSON config (transform a file in place) ----------------
def _setup_term3(repo: Path) -> None:
    _w(repo, "config.json",
       '{"name": "app", "version": "1.0.0", "debug": true, "port": 8080}\n')

_ORACLE_TERM3 = (
    "import json\n"
    "def test_config_edited():\n"
    "    c = json.load(open('config.json'))\n"
    "    assert c['debug'] is False, 'debug must be false'\n"
    "    assert c['port'] == 9090, 'port must be 9090'\n"
    "    assert c['version'] == '1.0.0', 'version must be unchanged'\n"
    "    assert c['name'] == 'app'\n"
)

# --- term4: grep-and-count style data extraction ------------------------------
def _setup_term4(repo: Path) -> None:
    _w(repo, "access.log",
       "GET /a 200\nPOST /b 404\nGET /c 200\nGET /d 500\nPOST /e 200\n"
       "GET /f 404\nGET /g 200\n")

_ORACLE_TERM4 = (
    "def test_counts():\n"
    "    c = open('counts.txt').read().strip().splitlines()\n"
    "    d = dict(line.split() for line in c)\n"
    "    assert d['200'] == '4'\n"
    "    assert d['404'] == '2'\n"
    "    assert d['500'] == '1'\n"
)

# --- term5: build a tiny CLI that takes args ----------------------------------
def _setup_term5(repo: Path) -> None:
    _w(repo, "README.md", "Build greet.py.\n")

_ORACLE_TERM5 = (
    "import subprocess\n"
    "def test_cli_args():\n"
    "    r = subprocess.run(['python','greet.py','World'], capture_output=True, text=True)\n"
    "    assert r.stdout.strip() == 'Hello, World!', f'got {r.stdout!r}'\n"
    "    r2 = subprocess.run(['python','greet.py','Bob'], capture_output=True, text=True)\n"
    "    assert r2.stdout.strip() == 'Hello, Bob!'\n"
)

# --- term6: fix a broken shell-invoked script ---------------------------------
def _setup_term6(repo: Path) -> None:
    _w(repo, "wordcount.py",
       "import sys\n"
       "def main():\n"
       "    text = open(sys.argv[1]).read()\n"
       "    print(len(text))           # BUG: prints CHAR count, not WORD count\n"
       "main()\n")
    _w(repo, "sample.txt", "the quick brown fox jumps\n")

_ORACLE_TERM6 = (
    "import subprocess\n"
    "def test_word_count():\n"
    "    r = subprocess.run(['python','wordcount.py','sample.txt'],\n"
    "                       capture_output=True, text=True)\n"
    "    assert r.stdout.strip() == '5', f'got {r.stdout!r}'\n"
)

# --- term7: create a directory structure --------------------------------------
def _setup_term7(repo: Path) -> None:
    _w(repo, "README.md", "Scaffold a project.\n")

_ORACLE_TERM7 = (
    "import os\n"
    "def test_scaffold():\n"
    "    for p in ['proj/__init__.py','proj/core.py','proj/tests/__init__.py',\n"
    "              'proj/tests/test_core.py']:\n"
    "        assert os.path.exists(p), f'missing {p}'\n"
    "    # core.py must define add()\n"
    "    import sys; sys.path.insert(0, '.')\n"
    "    from proj.core import add\n"
    "    assert add(2,3) == 5\n"
)

# --- term8: data pipeline — read, transform, write ----------------------------
def _setup_term8(repo: Path) -> None:
    _w(repo, "numbers.txt", "5\n3\n8\n1\n9\n2\n7\n")

_ORACLE_TERM8 = (
    "def test_sorted_unique_top3():\n"
    "    out = open('top3.txt').read().strip().splitlines()\n"
    "    assert out == ['9','8','7'], f'got {out}'\n"
)

_PYTEST_TERM = "python -m pytest -q -p no:cacheprovider tests/test_oracle.py"


# ===========================================================================
# THE SUITE
# ===========================================================================

SUITE: tuple[Task, ...] = (
    # ---- SWE family (hidden pytest oracle) ----
    Task("swe1_daterange", "swe",
         "There is a bug in daterange.py. `days_between(start, end)` is documented "
         "to return all dates from start to end INCLUSIVE, but it excludes the end "
         "date. Fix it so the end date is included and a single-day range returns "
         "that one day. Keep the existing sanity test passing. Commit your fix.",
         _setup_swe1, {"tests/test_oracle.py": _ORACLE_SWE1}, _PYTEST,
         note="off-by-one fix"),
    Task("swe2_lru", "swe",
         "lru.py's LRUCache is supposed to be a least-recently-used cache, but when "
         "it evicts it pops an arbitrary key instead of the least-recently-used one. "
         "A `get` should count as a use. Fix the eviction so the genuinely "
         "least-recently-used entry is removed when capacity is exceeded. Commit.",
         _setup_swe2, {"tests/test_oracle.py": _ORACLE_SWE2}, _PYTEST,
         note="LRU eviction correctness"),
    Task("swe3_split", "swe",
         "split.py's `split_bill(total_cents, n)` drops the remainder cents so the "
         "shares don't sum to the total. Fix it so the shares always sum exactly to "
         "total_cents, distributing the remainder one cent at a time, and the spread "
         "between the largest and smallest share is at most one cent. Commit.",
         _setup_swe3, {"tests/test_oracle.py": _ORACLE_SWE3}, _PYTEST,
         note="remainder distribution"),
    Task("swe4_email", "swe",
         "validate.py's `is_valid_email` uses a buggy regex: the dot is unescaped "
         "and the pattern isn't anchored, so it accepts strings with trailing junk "
         "and matches substrings. Fix the regex so it requires exactly "
         "letters@letters.letters with nothing extra. Commit.",
         _setup_swe4, {"tests/test_oracle.py": _ORACLE_SWE4}, _PYTEST,
         note="regex anchor/escape"),
    Task("swe5_counter", "swe",
         "counter.py has a classic shared-mutable-class-attribute bug: `instances` "
         "is a class attribute, so every Counter shares one list. Fix it so each "
         "Counter instance tracks only its own bumps. Commit.",
         _setup_swe5, {"tests/test_oracle.py": _ORACLE_SWE5}, _PYTEST,
         note="mutable class attr"),
    Task("swe6_roman", "swe",
         "roman.py has a `to_roman(n)` stub that raises NotImplementedError. "
         "Implement it per the spec in the file: convert an integer 1..3999 to its "
         "Roman numeral string, including subtractive forms (4=IV, 9=IX, 40=XL, "
         "1994=MCMXCIV). Commit.",
         _setup_swe6, {"tests/test_oracle.py": _ORACLE_SWE6}, _PYTEST,
         note="implement from spec"),
    Task("swe7_median", "swe",
         "stats.py's `median` returns the wrong value for an even number of "
         "elements (it should be the mean of the two middle values) and crashes "
         "unhelpfully on an empty list. Fix even-length handling and make an empty "
         "list raise ValueError or IndexError. Commit.",
         _setup_swe7, {"tests/test_oracle.py": _ORACLE_SWE7}, _PYTEST,
         note="even-case + edge"),
    Task("swe8_geom", "swe",
         "geom/shapes.py's `circle_area` forgot to square the radius (it returns "
         "pi*r instead of pi*r**2). This propagates through geom/calc.py's "
         "total_area. Fix circle_area; total_area should then be correct. Commit.",
         _setup_swe8, {"tests/test_oracle.py": _ORACLE_SWE8}, _PYTEST,
         note="cross-file logic"),
    Task("swe9_csv", "swe",
         "csvparse.py's `parse_line` splits naively on commas, so it breaks fields "
         "that are double-quoted and contain commas. Fix it so a quoted field like "
         "\"b,c\" is returned as the single value b,c (quotes stripped), while plain "
         "lines still split normally. Commit.",
         _setup_swe9, {"tests/test_oracle.py": _ORACLE_SWE9}, _PYTEST,
         note="quoted-field parsing"),
    Task("swe10_flatten", "swe",
         "flatten.py is meant to fully flatten arbitrarily nested lists into a flat "
         "list, but it appends nested results instead of extending, so nesting "
         "survives. Fix it so flatten([1,[2,[3,4]],5]) == [1,2,3,4,5]. Commit.",
         _setup_swe10, {"tests/test_oracle.py": _ORACLE_SWE10}, _PYTEST,
         note="recursive flatten"),
    Task("swe11_duration", "swe",
         "duration.py's `humanize(seconds)` computes minutes wrong (it uses "
         "seconds//60 for the minutes field instead of (seconds%3600)//60), so the "
         "minutes are inflated. Fix it to match the spec in the docstring: "
         "3661 -> '1h 1m 1s'. Commit.",
         _setup_swe11, {"tests/test_oracle.py": _ORACLE_SWE11}, _PYTEST,
         note="time decomposition"),
    Task("swe12_brackets", "swe",
         "brackets.py's `balanced` pops the stack on any closing bracket without "
         "checking it matches the most recent opener, so '(]' is wrongly reported "
         "balanced. Fix it to verify each closer matches the corresponding opener. "
         "Commit.",
         _setup_swe12, {"tests/test_oracle.py": _ORACLE_SWE12}, _PYTEST,
         note="stack matching"),

    # ---- TERM family (hidden command-output oracle) ----
    Task("term1_fizzbuzz", "term",
         "Create a file named out.txt in the current directory containing the "
         "FizzBuzz sequence for the numbers 1 through 15, one entry per line: print "
         "the number, except multiples of 3 become 'Fizz', multiples of 5 become "
         "'Buzz', and multiples of both become 'FizzBuzz'. Commit out.txt.",
         _setup_term1, {"tests/test_oracle.py": _ORACLE_TERM1}, _PYTEST_TERM,
         note="exact-output file"),
    Task("term2_sum", "term",
         "data.txt contains one integer per line. Write a script sum.py that reads "
         "data.txt and prints the sum of those integers (just the number) to stdout. "
         "Commit sum.py.",
         _setup_term2, {"tests/test_oracle.py": _ORACLE_TERM2}, _PYTEST_TERM,
         note="read+compute script"),
    Task("term3_config", "term",
         "Edit config.json in place: set \"debug\" to false and \"port\" to 9090, "
         "leaving every other field (name, version) unchanged. Keep it valid JSON. "
         "Commit config.json.",
         _setup_term3, {"tests/test_oracle.py": _ORACLE_TERM3}, _PYTEST_TERM,
         note="in-place JSON edit"),
    Task("term4_logcount", "term",
         "access.log has lines ending in an HTTP status code. Write a file "
         "counts.txt where each line is '<status> <count>' giving how many times "
         "each status code appears (any order). Commit counts.txt.",
         _setup_term4, {"tests/test_oracle.py": _ORACLE_TERM4}, _PYTEST_TERM,
         note="aggregate counts"),
    Task("term5_greet", "term",
         "Write a CLI script greet.py that takes one command-line argument (a name) "
         "and prints exactly 'Hello, <name>!' to stdout. For example "
         "`python greet.py World` prints 'Hello, World!'. Commit greet.py.",
         _setup_term5, {"tests/test_oracle.py": _ORACLE_TERM5}, _PYTEST_TERM,
         note="argv CLI"),
    Task("term6_wordcount", "term",
         "wordcount.py is supposed to print the number of WORDS in the file named "
         "by its first argument, but it prints the character count instead. Fix it "
         "so `python wordcount.py sample.txt` prints the word count. Commit.",
         _setup_term6, {"tests/test_oracle.py": _ORACLE_TERM6}, _PYTEST_TERM,
         note="fix shell script"),
    Task("term7_scaffold", "term",
         "Scaffold a Python package: create proj/__init__.py, proj/core.py (with a "
         "function add(a,b) returning a+b), proj/tests/__init__.py, and "
         "proj/tests/test_core.py. Commit all of them.",
         _setup_term7, {"tests/test_oracle.py": _ORACLE_TERM7}, _PYTEST_TERM,
         note="dir scaffolding"),
    Task("term8_pipeline", "term",
         "numbers.txt has one integer per line. Write a file top3.txt containing the "
         "three largest DISTINCT values, one per line, in descending order. Commit "
         "top3.txt.",
         _setup_term8, {"tests/test_oracle.py": _ORACLE_TERM8}, _PYTEST_TERM,
         note="sort/unique/slice"),
)


def setup_repo(task: Task, repo: Path) -> None:
    """Seed `repo` with the task's buggy/initial files + an initial git commit.
    Does NOT write the oracle (the agent must never see the grading test)."""
    import subprocess

    def g(*a):
        subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True)

    g("init", "-q")
    g("config", "user.email", "bench@dos")
    g("config", "user.name", "bench")
    g("config", "commit.gpgsign", "false")
    task.setup(repo)
    g("add", "-A")
    g("commit", "-q", "-m", "initial: task seed")

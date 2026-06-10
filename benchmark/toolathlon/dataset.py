"""Dataset I/O: download + stream the `hkust-nlp/Toolathlon-Trajectories` JSONL files.

This is the only module that touches the network/disk — the boundary, kept apart from the pure
reader (`trajectory.py`) and the pure scorer (`replay.py`) so those stay replay-testable with zero
network. Files are large (one record can be MBs); we stream line-by-line, never load a whole file
into a list unless asked.

The dataset (CC-BY-4.0): 22 models x 3 runs = 66 JSONL files, each ~108 task records, named
`<model>_<run>.jsonl` (the published set grew from the original 17x3=51; `list_files` reads it live
from the HF API, so it tracks whatever is published). Resolve URL:
    https://huggingface.co/datasets/hkust-nlp/Toolathlon-Trajectories/resolve/main/<file>
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Iterator, Optional

from .trajectory import Trajectory, parse_record

_HF_API = "https://huggingface.co/api/datasets/hkust-nlp/Toolathlon-Trajectories"
_HF_RESOLVE = "https://huggingface.co/datasets/hkust-nlp/Toolathlon-Trajectories/resolve/main"
_UA = {"User-Agent": "dos-toolathlon-replay/1.0"}

# Where downloaded JSONL is cached. Gitignored (the files are large + CC-BY, not ours to vendor).
DEFAULT_CACHE = Path(os.environ.get("TOOLATHLON_CACHE", str(Path(__file__).parent / "_data")))


def list_files() -> list[str]:
    """The `<model>_<run>.jsonl` files in the dataset, via the HF datasets API."""
    req = urllib.request.Request(_HF_API, headers=_UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        meta = json.loads(r.read().decode("utf-8"))
    return sorted(
        s["rfilename"] for s in meta.get("siblings", []) if s["rfilename"].endswith(".jsonl")
    )


def ensure_file(filename: str, cache_dir: Path = DEFAULT_CACHE) -> Path:
    """Download `filename` into the cache if absent; return the local path. Idempotent."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / filename
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    url = f"{_HF_RESOLVE}/{filename}"
    req = urllib.request.Request(url, headers=_UA)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(dest)
    return dest


def iter_trajectories(
    path: Path, *, limit: Optional[int] = None
) -> Iterator[Trajectory]:
    """Stream `Trajectory` objects from a local JSONL file. Skips blank/malformed lines (a corrupt
    record is logged-by-skip, never aborts the run)."""
    n = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            yield parse_record(rec)
            n += 1
            if limit is not None and n >= limit:
                return


def load_corpus(
    files: list[str],
    *,
    cache_dir: Path = DEFAULT_CACHE,
    per_file_limit: Optional[int] = None,
    download: bool = True,
) -> Iterator[Trajectory]:
    """Stream trajectories across many files. With `download=True`, fetches any missing file first;
    with `download=False`, reads only what is already cached (offline / replay-only)."""
    for fn in files:
        if download:
            path = ensure_file(fn, cache_dir)
        else:
            path = cache_dir / fn
            if not path.exists():
                continue
        yield from iter_trajectories(path, limit=per_file_limit)

"""dos_react orchestrator registration shim (docs/143).

The logic lives in the DOS repo (`benchmark/enterpriseops/dos_react.py`, a consumer of the
`dos` kernel). That file is NOT part of the pip-installed `dos` package (only `src/dos/` is
packaged), and the gym has its own `benchmark/` package, so we load the consumer module by
ABSOLUTE FILE PATH via importlib — a single source of truth, no copy to drift. It imports
only `dos.arg_provenance`, which IS pip-installed into the gym venv.

Set DOS_REPO to override the repo location (default: the DOS repo this shim lives in,
derived from __file__).
"""
import importlib.util
import os

# This shim lives at <dos-repo>/benchmark/enterpriseops/gym_orchestrator_shim.py, so the
# repo root is two parents up. DOS_REPO overrides it (e.g. when the shim is copied elsewhere).
_DEFAULT_DOS_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DOS_REPO = os.environ.get("DOS_REPO", _DEFAULT_DOS_REPO)
_CONSUMER = os.path.join(_DOS_REPO, "benchmark", "enterpriseops", "dos_react.py")

_spec = importlib.util.spec_from_file_location("dos_enterpriseops_dos_react", _CONSUMER)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

make_dos_react_orchestrator = _mod.make_dos_react_orchestrator
DosReactOrchestrator = make_dos_react_orchestrator()

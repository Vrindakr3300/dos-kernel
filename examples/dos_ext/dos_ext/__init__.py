"""dos_ext — a copy-me example DOS extension package.

Ships both behavior-axis plugins (HACKING.md), registered under their
entry-point groups in this package's `pyproject.toml`:
  * the `terse` renderer (`dos_ext.renderer`) under `dos.renderers` — Axis 4.
  * the `budget_guard` admission predicate (`dos_ext.predicates`) under
    `dos.predicates` — Axis 3 (the conjunctive-only safety seam).

`pip install -e examples/dos_ext` makes `dos --output terse` resolve the renderer
and the arbiter pick up the predicate, without the `dos` package knowing this one
exists.
"""

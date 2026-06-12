"""Pin the GitLab CI template (gitlab-ci/dos-verify.gitlab-ci.yml, issue #73).

The same discipline test_workflow_yaml_parses applies to .github/workflows —
a template that doesn't parse, or that silently loses its load-bearing knobs
(the full-clone GIT_DEPTH, the verdict-is-the-exit-code script, the MR rule),
ships broken to every consumer who `include:`s it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "gitlab-ci" / "dos-verify.gitlab-ci.yml"
)


def _load() -> dict:
    return yaml.safe_load(_TEMPLATE.read_text(encoding="utf-8"))


def test_template_parses_and_has_the_job() -> None:
    doc = _load()
    assert "dos-verify" in doc, "the named job IS the consumer contract"


def test_full_clone_is_forced() -> None:
    # The audit reads ancestry; GitLab's default shallow clone amputates it.
    job = _load()["dos-verify"]
    assert job["variables"]["GIT_DEPTH"] == "0"


def test_runs_on_merge_requests() -> None:
    job = _load()["dos-verify"]
    conditions = [r.get("if", "") for r in job["rules"]]
    assert any("merge_request_event" in c for c in conditions)


def test_script_carries_both_verdicts_and_the_observe_mode() -> None:
    job = _load()["dos-verify"]
    script = "\n".join(job["script"])
    assert "commit-audit --sweep" in script
    assert "CI_MERGE_REQUEST_DIFF_BASE_SHA" in script   # MR base..head default
    assert "--warn-only" in script                       # DOS_FAIL_ON=none path
    assert "dos verify" in script                        # the optional phase rung


def test_install_pin_is_overridable_and_names_the_real_dist() -> None:
    job = _load()["dos-verify"]
    before = "\n".join(job["before_script"])
    # The dist name is dos-kernel (the bare `dos` on PyPI is a squatter), and
    # DOS_VERSION concatenates a pip version spec for reproducible CI.
    assert 'dos-kernel${DOS_VERSION}' in before

"""Vertex AI supervised-tuning launcher for the Payoff-2 arm (docs/231).

Drives the REAL train-and-measure arm: stage the poison|clean SFT JSONL to GCS, create two
Vertex supervised tuning jobs on `gemini-2.5-flash` (the same family the data was generated
with), poll to completion, return the tuned-model endpoints. The held-out J2 eval then runs
through `rlvr_eval.py`.

AUTH: uses the gcloud USER token via REST (ADC was broken by a set-quota-project reauth; the
user token reaches the Vertex tuningJobs endpoint fine — verified HTTP 200). No SDK/ADC.

WHY REST, NOT THE SDK: the genai SDK defaults to ADC; rather than fight that, we POST the
tuningJobs.create contract directly. Lessons baked in (learned the hard way, docs/231):
  * tuningJobs.create EXECUTES IMMEDIATELY — there is no dry-run; a bad dataset URI still
    creates a RUNNING job that then fails validation. Validate inputs before calling.
  * `gemini-2.5-flash` / `-flash-lite` / `-pro` are tunable in us-central1; `2.0-flash`,
    `2.5-flash-002`, `1.5-flash-002` are NOT (400 "Base model ... is not supported").
  * cancel = POST `.../tuningJobs/{id}:cancel` with an explicit `Content-Length: 0` header
    (else HTTP 411).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

_GCLOUD = r"C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
# Set DOS_RLVR_PROJECT to your own GCP project (the tuning runs were one-off).
_PROJECT = os.environ.get("DOS_RLVR_PROJECT", "<your-gcp-project>")
_LOCATION = "us-central1"
_BASE_MODEL = "gemini-2.5-flash"


def _token() -> str:
    """The gcloud USER access token (ADC is broken; the user token reaches Vertex)."""
    out = subprocess.run([_GCLOUD, "auth", "print-access-token"],
                         capture_output=True, text=True, timeout=60)
    return out.stdout.strip()


def _api(method: str, path: str, body: Optional[dict] = None, *, version: str = "v1") -> dict:
    """One Vertex REST call against the regional endpoint. Raises on HTTP error with the body."""
    url = f"https://{_LOCATION}-aiplatform.googleapis.com/{version}/{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else b""
    headers = {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json",
               "Content-Length": str(len(data))}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"Vertex {method} {path} -> HTTP {e.code}: {detail[:500]}") from None


# --- GCS staging (via gcloud storage; no SDK) ------------------------------------------


def ensure_bucket(bucket: str) -> None:
    """Create the GCS bucket if absent (idempotent)."""
    chk = subprocess.run([_GCLOUD, "storage", "buckets", "describe", f"gs://{bucket}",
                          "--project", _PROJECT, "--format=value(name)"],
                         capture_output=True, text=True, timeout=60)
    if chk.returncode == 0:
        return
    subprocess.run([_GCLOUD, "storage", "buckets", "create", f"gs://{bucket}",
                    "--project", _PROJECT, "--location", _LOCATION],
                   capture_output=True, text=True, timeout=120, check=True)


def stage_jsonl(local_path: str, gcs_uri: str) -> None:
    """Copy a local JSONL up to GCS (gs://bucket/key)."""
    subprocess.run([_GCLOUD, "storage", "cp", local_path, gcs_uri, "--project", _PROJECT],
                   capture_output=True, text=True, timeout=300, check=True)


# --- tuning jobs ------------------------------------------------------------------------


@dataclass(frozen=True)
class TuningJob:
    arm: str
    job_id: str
    name: str
    state: str
    tuned_model_endpoint: Optional[str] = None


def create_tuning_job(arm: str, training_gcs_uri: str, *, epochs: int = 3,
                      base_model: str = _BASE_MODEL, display: Optional[str] = None) -> TuningJob:
    """Create one supervised tuning job. Returns the job handle (state RUNNING/PENDING).

    `arm` is 'poison'|'clean' (display/label only). `epochs` is the tuning epoch count
    (kept identical across arms so the only variable is the dataset).
    """
    body = {
        "baseModel": base_model,
        "tunedModelDisplayName": (display or f"rlvr-admit-{arm}")[:40],
        "supervisedTuningSpec": {
            "trainingDatasetUri": training_gcs_uri,
            "hyperParameters": {"epochCount": str(epochs)},
        },
    }
    j = _api("POST", f"projects/{_PROJECT}/locations/{_LOCATION}/tuningJobs", body)
    name = j.get("name", "")
    return TuningJob(arm=arm, job_id=name.split("/")[-1], name=name,
                     state=j.get("state", "JOB_STATE_UNSPECIFIED"))


def get_job(job_id: str) -> dict:
    return _api("GET", f"projects/{_PROJECT}/locations/{_LOCATION}/tuningJobs/{job_id}")


def cancel_job(job_id: str) -> None:
    """Cancel a tuning job (Content-Length:0 is supplied by _api)."""
    _api("POST", f"projects/{_PROJECT}/locations/{_LOCATION}/tuningJobs/{job_id}:cancel")


_TERMINAL = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}


def poll_until_done(job_id: str, *, interval_s: int = 60, timeout_s: int = 9000) -> dict:
    """Poll a tuning job to a terminal state. Returns the final job dict.

    NB: meant to be called from a BACKGROUND runner — tuning takes tens of minutes. The
    caller persists the job-ids first so a restart can re-attach without re-spending.
    """
    waited = 0
    while waited < timeout_s:
        j = get_job(job_id)
        st = j.get("state", "")
        if st in _TERMINAL:
            return j
        time.sleep(interval_s)
        waited += interval_s
    return get_job(job_id)


def tuned_endpoint(job: dict) -> Optional[str]:
    """The served tuned-model endpoint resource from a SUCCEEDED job (for inference)."""
    tm = job.get("tunedModel", {}) or {}
    return tm.get("endpoint") or tm.get("model")

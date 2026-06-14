"""_drive_cpu_model.py — generate REAL on-device-tier trajectories on CPU (docs/341 §4).

The genuine sub-1B datapoint the replay corpus lacks: drive a tiny instruct model that
actually fits on a phone (SmolLM2-135M-Instruct, ~270 MB, or any --model), on CPU, over
a handful of tool-use tasks, and DUMP each run as a `Trajectory`-compatible JSON so
`harness.py --recordings` folds the real kernel detectors over it.

This is deliberately small and honest: a few scripted tasks, a minimal tool loop, a
hard step cap. It is NOT a benchmark of the model's task success — it is a way to
observe what failure SHAPES a genuinely phone-tier model produces, and whether the
byte-clean detectors fire on them. The detectors read the dumped trajectory; this
script authors only the trajectory, never a verdict.

The leading underscore keeps it out of the $0 `sweep` entrypoint (it needs torch +
a model download); it is an opt-in tool, run by hand:

    pip install --user --index-url https://download.pytorch.org/whl/cpu torch
    pip install --user transformers
    python -m benchmark.smartphone_tier._drive_cpu_model --out /tmp/smol_runs
    python -m benchmark.smartphone_tier.harness --recordings /tmp/smol_runs --tier-name SmolLM2-135M

No network/model bytes enter the repo; --out is a scratch dir (keep it gitignored).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# A tiny scripted tool world. Each task gives the model a goal and ONE tool it
# must call to finish. The env authors every tool RESULT (the byte-clean surface).
# The tasks are chosen to expose phone-tier failure shapes: a multi-step goal a
# small model tends to narrate-then-abandon (dangle), and a lookup it tends to
# re-issue (loop).
# ---------------------------------------------------------------------------
_DB = {
    "INC0010023": {"status": "open", "team": "network"},
    "users": {"U7": "Alex", "U9": "Sam"},
    "groups": {"G1": []},
}


def _tool_exec(name: str, args: Dict[str, object]) -> Tuple[str, bool]:
    """Run one tool call against the scripted world. Returns (result_text, mutated).
    The ENV authors this string — the agent cannot forge it (the byte-clean rule)."""
    if name == "get_incident":
        inc = _DB.get(str(args.get("id", "")))
        return (json.dumps(inc) if inc else json.dumps({"error": "not found"})), False
    if name == "get_user":
        u = _DB["users"].get(str(args.get("id", "")))
        return (json.dumps({"name": u}) if u else json.dumps({"error": "not found"})), False
    if name == "add_group_member":
        gid = str(args.get("group", ""))
        uid = str(args.get("user", ""))
        if gid in _DB["groups"] and uid in _DB["users"]:
            _DB["groups"][gid].append(uid)
            return json.dumps({"ok": True, "members": _DB["groups"][gid]}), True
        return json.dumps({"error": "bad group or user"}), False
    return json.dumps({"error": f"unknown tool {name}"}), False


_TASKS = [
    {
        "task_id": "assign-member",
        "goal": ("Add user U7 to group G1. First call get_user with id U7 to confirm "
                 "the user exists, then call add_group_member with group G1 and user U7."),
        "success_tool": "add_group_member",
    },
    {
        "task_id": "lookup-incident",
        "goal": ("Find the status of incident INC0010023 by calling get_incident with "
                 "id INC0010023, then report the status and stop."),
        "success_tool": "get_incident",
    },
]


_SYS = (
    "You are an agent with tools. To call a tool, output EXACTLY one line:\n"
    'CALL <tool_name> {"arg": "value"}\n'
    "Available tools: get_incident{id}, get_user{id}, add_group_member{group,user}.\n"
    "When the goal is done, output: DONE\n"
    "Call one tool per turn. Do not explain."
)

_CALL_RE = re.compile(r'CALL\s+(\w+)\s*(\{.*\})', re.IGNORECASE)


def _parse_call(text: str) -> Optional[Tuple[str, Dict[str, object]]]:
    m = _CALL_RE.search(text)
    if not m:
        return None
    tool = m.group(1)
    try:
        args = json.loads(m.group(2))
    except Exception:
        return None
    return tool, (args if isinstance(args, dict) else {})


def _digest(s: str) -> str:
    import hashlib
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def drive_one(model, tokenizer, task: dict, max_steps: int = 6) -> dict:
    """Run one task to completion or the step cap. Returns a Trajectory-shaped dict
    (the schema harness._traj_from_record reads)."""
    import torch  # local import: only needed when actually driving

    messages = [{"role": "system", "content": _SYS},
                {"role": "user", "content": task["goal"]}]
    steps: List[Tuple[str, str, Optional[str]]] = []
    last_text = ""
    succeeded = False
    results_after = 0

    for _ in range(max_steps):
        prompt = tokenizer.apply_chat_template(messages, tokenize=False,
                                               add_generation_prompt=True)
        inputs = tokenizer(prompt, return_tensors="pt")
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=64, do_sample=False,
                                 pad_token_id=tokenizer.eos_token_id)
        text = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:],
                                skip_special_tokens=True).strip()
        last_text = text
        messages.append({"role": "assistant", "content": text})

        call = _parse_call(text)
        if call is None:
            # no tool call this turn — the run stops here (DONE or narration).
            break
        tool, args = call
        result, mutated = _tool_exec(tool, args)
        steps.append((tool, _digest(json.dumps(args, sort_keys=True)), _digest(result)))
        results_after += 1  # a real tool ran after this turn's narration
        messages.append({"role": "user", "content": f"RESULT: {result}"})
        if mutated and tool == task["success_tool"]:
            succeeded = True
            # let it emit a final DONE turn (so results_after resets correctly below)
        if "DONE" in text.upper():
            break

    # the terminal turn is `last_text`; results_after for the DANGLE detector is the
    # count of tool results that landed strictly AFTER it — 0 if the last turn was
    # narration with no call (the common phone-tier premature stop).
    final_call = _parse_call(last_text)
    results_after_terminal = 0 if final_call is None else 1
    return {
        "task_id": task["task_id"],
        "failed": not succeeded,
        "final_turn": last_text,
        "results_after": results_after_terminal,
        "steps": [{"tool": t, "args_digest": a, "result_digest": r} for (t, a, r) in steps],
        "env_blobs": [],   # this tiny world has no minted-id surface; left empty
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="drive a tiny CPU model and dump trajectories")
    p.add_argument("--model", default="HuggingFaceTB/SmolLM2-135M-Instruct",
                   help="a small instruct model id (default: SmolLM2-135M-Instruct, ~270MB)")
    p.add_argument("--out", required=True, help="scratch dir for the per-run JSON dumps")
    p.add_argument("--repeats", type=int, default=3,
                   help="runs per task (a small model is non-deterministic across prompts)")
    args = p.parse_args(argv)

    try:
        import torch  # noqa: F401
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except Exception as e:
        print(f"need torch + transformers: {e}\n"
              "  pip install --user --index-url https://download.pytorch.org/whl/cpu torch\n"
              "  pip install --user transformers", file=sys.stderr)
        return 2

    print(f"loading {args.model} on CPU (first run downloads the weights)…", file=sys.stderr)
    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(args.model)
    model.eval()

    os.makedirs(args.out, exist_ok=True)
    n = 0
    for task in _TASKS:
        for r in range(args.repeats):
            rec = drive_one(model, tok, task)
            path = os.path.join(args.out, f"{task['task_id']}_{r}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rec, f, indent=2)
            n += 1
            print(f"  [{n}] {task['task_id']} run {r}: "
                  f"{'PASS' if not rec['failed'] else 'FAIL'} "
                  f"({len(rec['steps'])} tool calls)", file=sys.stderr)
    print(f"wrote {n} trajectories to {args.out}\n"
          f"fold them: python -m benchmark.smartphone_tier.harness --recordings {args.out} "
          f"--tier-name {args.model.split('/')[-1]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

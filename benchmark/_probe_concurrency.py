"""One-shot probe: measure temporal concurrency + tool usage across the CC
trajectory corpus for this repo. Scratch — not part of the kernel."""
import json, glob, collections, datetime, os

CORPUS = os.path.expanduser("~/.claude/projects/<project>")


def parse(t):
    try:
        return datetime.datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    except Exception:
        return None


def main():
    sessions = []
    for f in glob.glob(os.path.join(CORPUS, "*.jsonl")):
        branch = cwd = None
        ts = []
        nass = 0
        tools = collections.Counter()
        sidechain = False
        try:
            for line in open(f, encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("gitBranch") and branch is None:
                    branch = r.get("gitBranch")
                if r.get("cwd") and cwd is None:
                    cwd = r.get("cwd")
                if r.get("isSidechain"):
                    sidechain = True
                t = r.get("timestamp")
                if t:
                    ts.append(t)
                if r.get("type") == "assistant":
                    nass += 1
                    msg = r.get("message", {})
                    if isinstance(msg, dict):
                        for b in (msg.get("content") or []):
                            if isinstance(b, dict) and b.get("type") == "tool_use":
                                tools[b.get("name", "?")] += 1
        except Exception:
            continue
        if ts:
            ts.sort()
            sessions.append(
                dict(
                    f=os.path.basename(f), branch=branch, cwd=cwd,
                    start=ts[0], end=ts[-1], nass=nass,
                    tools=sum(tools.values()), tooldist=tools, sidechain=sidechain,
                )
            )

    print(f"sessions with timestamps: {len(sessions)}")
    br = collections.Counter(s["branch"] for s in sessions)
    print("branches:", dict(br.most_common(10)))

    needle = os.path.join("work", "dos").lower()
    dos = []
    for s in sessions:
        c = (s["cwd"] or "").lower().replace("/", os.sep).replace("\\", os.sep)
        if needle in c and not s["sidechain"]:
            s["s"] = parse(s["start"]) ; s["e"] = parse(s["end"])
            if s["s"] and s["e"] and s["nass"] >= 3:
                dos.append(s)
    print(f"\nreal dos-repo sessions (>=3 assistant turns, not sidechain): {len(dos)}")

    dos.sort(key=lambda s: s["s"])
    events = []
    for s in dos:
        events.append((s["s"], 1)); events.append((s["e"], -1))
    events.sort(key=lambda x: (x[0], x[1]))
    cur = max_c = 0
    for t, d in events:
        cur += d
        max_c = max(max_c, cur)

    overlapping = set()
    for i in range(len(dos)):
        ei = dos[i]["e"]
        for j in range(i + 1, len(dos)):
            if dos[j]["s"] < ei:
                overlapping.add(dos[i]["f"]); overlapping.add(dos[j]["f"])
            else:
                break
    print(f"max concurrent sessions at one instant: {max_c}")
    print(f"sessions overlapping >=1 other (approx): {len(overlapping)} / {len(dos)}")

    allstart = min(s["s"] for s in dos); allend = max(s["e"] for s in dos)
    print(f"corpus span: {allstart.date()} .. {allend.date()} ({(allend-allstart).days} days)")

    # aggregate tool distribution across substantial dos sessions
    agg = collections.Counter()
    for s in dos:
        agg.update(s["tooldist"])
    print("\naggregate tool calls across substantial dos sessions:")
    for name, n in agg.most_common(15):
        print(f"  {n:6d}  {name}")
    print(f"  total tool calls: {sum(agg.values())}")


if __name__ == "__main__":
    main()

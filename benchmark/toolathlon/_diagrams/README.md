# EXPLAINER diagrams

High-resolution PNG renders of the four Mermaid diagrams embedded in
`../EXPLAINER.md`. Many Markdown viewers don't render ` ```mermaid ` fenced
blocks, so the PNGs are committed alongside the source and referenced inline in
the EXPLAINER so the diagrams always show up.

| Source (`.mmd`) | Render (`.png`) | EXPLAINER section |
|---|---|---|
| `diagram1_replay_pipeline.mmd` | `diagram1_replay_pipeline.png` | §2 — the replay pipeline |
| `diagram2_what_each_detector_sees.mmd` | `diagram2_what_each_detector_sees.png` | §2 — what each detector looks at |
| `diagram3_why_lift_sounds_bigger.mmd` | `diagram3_why_lift_sounds_bigger.png` | §3 — why "lift" sounds bigger than it is |
| `diagram4_precision_carries_signal_vanishes.mmd` | `diagram4_precision_carries_signal_vanishes.png` | §3 — precision carries, signal vanishes |

## Regenerate

The `.mmd` sources are the lift-and-shift of the fenced blocks in
`../EXPLAINER.md`. To re-render at 3× scale (high-resolution) with a white
background:

```bash
cd benchmark/toolathlon
npm install --no-save @mermaid-js/mermaid-cli   # one-time; node_modules is gitignored

# mermaid-cli needs a headless browser. If puppeteer can't find one, point it at
# a system Chrome/Edge via a puppeteer config:
#   echo '{"executablePath": "<path-to-chrome.exe>", "args": ["--no-sandbox"]}' > pup.json
# then add  -p pup.json  to each command below.

for d in _diagrams/*.mmd; do
  ./node_modules/.bin/mmdc -i "$d" -o "${d%.mmd}.png" -s 3 -b white
done
```

`node_modules/`, `package.json`, and `package-lock.json` are gitignored (the
mermaid-cli install is regenerable); the `.mmd` sources and `.png` renders in
this directory are the durable, committed deliverables.

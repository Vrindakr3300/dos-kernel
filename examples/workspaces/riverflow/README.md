# `riverflow` — data / ML pipeline workspace

An anonymized `ingest → train → serve` pipeline. The point of this fixture: a
**long-horizon exclusive lane**. The `train` lane holds a shared GPU box for
tens of minutes; `ingest` and `serve` run concurrently around it.

```text
ingest/         extract + load          →  lane: ingest
schemas/        data contracts          →  lane: ingest
train/          model training          →  lane: train  (exclusive — owns the GPU)
models/         checkpoints             →  lane: train
serve/          inference API           →  lane: serve
```

`train` is **exclusive** not because its files overlap anything, but because it
monopolizes a *resource* the file-tree algebra can't see (the accelerator). An
exclusive lane is admitted on liveness alone — it runs by itself.

```bash
dos doctor --workspace .                 # train shows under "exclusive lanes"
dos man lane train                       # EXCLUSIVITY: runs alone

# ingest and serve are disjoint → both admit:
dos arbitrate --workspace . --lane serve --kind cluster \
  --leases '[{"lane":"ingest","lane_kind":"cluster","tree":["ingest/**"]}]'
```

The walkthrough adds the temporal question — *is the training run advancing or
spinning?* — via `dos liveness`:
[`../../playbooks/04_data-ml-pipeline.md`](../../playbooks/04_data-ml-pipeline.md).

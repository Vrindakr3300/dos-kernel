# `gravel` — infra / platform monorepo workspace

An anonymized Terraform + k8s platform repo. The point of this fixture: **most
lanes are exclusive** because blast radius is real. A fleet here is mostly about
*refusing* unsafe concurrency, not maximizing it.

```text
modules/        reusable TF modules     →  lane: modules  (concurrent — pure code)
docs/runbooks/  operator docs           →  lane: docs     (concurrent)
live/           live TF state           →  lane: tfstate  (EXCLUSIVE — real cloud)
terraform/      root TF                 →  lane: tfstate  (EXCLUSIVE)
k8s/  helm/     cluster manifests       →  lane: cluster  (EXCLUSIVE — live cluster)
```

Three refusals this workspace is built to demonstrate:

```bash
# 1) Two loops both wanting the EXCLUSIVE tfstate lane → the second is refused:
dos arbitrate --workspace . --lane tfstate --kind global \
  --leases '[{"lane":"tfstate","lane_kind":"global","tree":["live/**"]}]'

# 2) The self-modify guard — a lease over the kernel's own code is always refused
#    (this is built-in, independent of gravel's lanes):
dos arbitrate --workspace . --lane modules --kind cluster --tree src/dos/arbiter.py --leases '[]'

# 3) A BLOCKED gate verdict — picks gated on a soak/operator window (see playbook 05).
```

> **Heads-up — `--check` here judges the parent repo.** This fixture isn't its
> own git repo, so `dos doctor --workspace . --check` reads the DOS repo's
> commits and (correctly) finds that `modules|live|k8s|docs` matches none of
> them — exit 1 with a finding. That's the completeness rail doing its job
> against the wrong history. In a real `gravel` checkout with `modules/NET: ...`
> ship commits it exits 0. See
> [playbook 06](../../playbooks/06_debug-a-stuck-fleet.md#the-stamp-check-finding-i-didnt-expect).

Full walkthrough: [`../../playbooks/05_infra-monorepo.md`](../../playbooks/05_infra-monorepo.md).

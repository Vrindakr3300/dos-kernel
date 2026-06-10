# `acme-store` — polyglot web-service workspace

An anonymized SaaS-storefront monorepo. The point of this fixture: **three
disjoint concurrent lanes** (`api`, `web`, `worker`) plus one **exclusive** lane
(`infra`), so a fleet can edit the backend and the frontend at the same time but
serializes anything that touches deploy/Terraform.

```text
src/api/        backend service        →  lane: api
src/shared/     shared types/util      →  lane: api  (shared tree)
web/            frontend app           →  lane: web
src/worker/     background jobs        →  lane: worker
deploy/         k8s + helm             →  lane: infra (exclusive)
terraform/      cloud infra            →  lane: infra (exclusive)
```

Try it:

```bash
dos doctor --workspace .                 # see the four lanes + the generic stamp grammar
dos man lane web                         # the web lane's tree + exclusivity

# api and web are disjoint → both admit concurrently:
dos arbitrate --workspace . --lane web --kind cluster \
  --leases '[{"lane":"api","lane_kind":"cluster","tree":["src/api/**"]}]'
#   outcome: acquire

# a second loop wanting the SAME lane as a live one → arbiter reassigns or refuses:
dos arbitrate --workspace . --lane api --kind cluster \
  --leases '[{"lane":"api","lane_kind":"cluster","tree":["src/api/**"]}]'
```

Full walkthrough: [`../../playbooks/02_polyglot-web-service.md`](../../playbooks/02_polyglot-web-service.md).

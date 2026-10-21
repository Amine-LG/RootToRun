# Installation and configuration

Pick the way that matches what you want to do.

| You want to | Use | Cluster access |
|---|---|---|
| Learn in a browser, or publish the site | [Static site](#static-site) | none |
| Run it locally, offline or in a classroom | [Container](#container) | none |
| Host it on Kubernetes or OpenShift | [Manifests](#kubernetes-manifests) | none |
| Run the labs for real on your own cluster | [Local cluster mode](#local-cluster-mode) | yes, local only |

## Static site

```bash
cd frontend && npm ci && npm run build && cd ..
uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt
ACADEMY_REPO_URL=https://github.com/your-account/your-fork \
  .venv/bin/python scripts/export_static.py --site-url https://your.domain   # both optional (see below)
python3 -m http.server --directory frontend/dist 8000                     # try it: http://localhost:8000
```

Publish `frontend/dist/` on any static host. `ACADEMY_REPO_URL` turns on the "Report an issue" and "Edit this lesson"
links; `--site-url` adds canonical URLs and a sitemap. The frontend build writes `licenses.txt` (every licence text the
site needs) and the export writes `version.json` (version and commit). Serve unknown paths with `404.html` (or `index.html`). The site must be
served from the root of its domain. The recommended security headers are the ones the container sets, in
[`deploy/nginx/nginx.conf`](../deploy/nginx/nginx.conf).

## Container

The production image: the static site served by an unprivileged nginx, nothing else (no server code, no cluster
client). Its nginx rules and headers: [`deploy/nginx/nginx.conf`](../deploy/nginx/nginx.conf).

```bash
podman build -t localhost/static-site:dev --build-arg BUILD_COMMIT=$(git rev-parse HEAD) .   # or: docker build -f Containerfile ...
podman run --rm -p 127.0.0.1:8080:8080 --read-only --tmpfs /tmp --cap-drop ALL localhost/static-site:dev
podman compose up -d                      # the same with compose.yaml (ACADEMY_PORT=9000 for another local port)
```

Open http://127.0.0.1:8080. It runs as a non-root user, works with any UID (OpenShift), needs no writable filesystem
except `/tmp`, and answers `GET /healthz` for probes.

## Kubernetes manifests

Build and push the image to a registry your cluster can pull from, then:

```bash
cd deploy/kubernetes
kustomize edit set image static-site=registry.example.com/team/site@sha256:<digest>
oc apply -k .                  # OpenShift (includes an edge Route); on other Kubernetes remove route.yaml and add an Ingress
```

Runs as `restricted-v2` on OpenShift: non-root, no privilege escalation, all capabilities dropped, read-only root
filesystem, no ServiceAccount token. A normal project admin can install it.

## Local cluster mode

For running the labs on your own **disposable** OpenShift cluster (OpenShift Local / CRC, or an OpenShift test
cluster). Labs create OpenShift projects (`oc new-project`), so a plain Kubernetes cluster is not supported.

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/), Node.js 22.12 or newer, `oc` 4.x on `PATH` (or OpenShift
Local's copy: `crc oc-env` prints how to add it); Helm 3 for the Helm lab and challenge.

The recordings were made on OpenShift Local 4.21.8. It needs a Red Hat account for the pull secret `crc start` asks for,
4 physical CPU cores, 10.5 GB of free memory and 35 GB of disk on a host with hardware virtualisation (Windows 11 except
Home, macOS 15 or later, recent RHEL, CentOS or Fedora; see [CRC: installing](https://crc.dev/docs/installing/)). It is a
single node with the monitoring operator disabled by default, so labs never show more than one node, cluster updates or
metrics. `crc console --credentials` prints the `developer` and `kubeadmin` passwords.

What each kind of activity needs from the cluster (the lab page's preflight checks it before anything is created):

| Activity | Needs |
|---|---|
| Every lab, incident and challenge | the learner identity, allowed to create projects (OpenShift Local's `developer`) |
| Steps or setup marked admin (`lab.groups`, `lab.sa-scc`, `lab.quotas-limits`) | the admin identity, after a typed confirmation |
| Steps that read the cluster (nodes, StorageClasses, catalogs, ClusterRoleBindings) | the reader identity, created once from the Connections page |
| `lab.scheduling` | OpenShift Local itself: its commands name the node `crc` |
| `lab.olm-inspect` | the Operator Lifecycle Manager APIs, present on every OpenShift cluster |
| `lab.storage`, `inc.pvc-pending` | a default StorageClass; with `reclaimPolicy: Retain` (OpenShift Local) a Released volume stays after cleanup |

```bash
./run.sh            # builds the frontend if needed, starts http://127.0.0.1:8768 (local only)
./stop.sh
```

Then open **My cluster → Connections**, connect the learner, and **approve the cluster for training labs** by typing
its API host. Until you do, the academy only reads from the cluster: preparing a lab, running a command that changes
something, connecting the admin identity and creating the reader are refused. The approval is stored in
`data/cluster-approvals.json` and bound to the learner kubeconfig's API address and certificate authority; if the
kubeconfig later points elsewhere (or stops verifying TLS), the academy is read-only again. Only approve a disposable
training cluster, never a production one.

| Identity | What it is | Permissions needed |
|---|---|---|
| learner | a normal user (CRC: `developer`) | self-provisioner (create projects); admin of the `academy-*` projects it creates |
| reader | a ServiceAccount the academy creates in `academy-system`, bound to `cluster-reader`, with a 24 h token | read-only cluster-wide, no Secrets |
| admin | optional (CRC: `kubeadmin`), typed confirmation | used only by labs marked as needing an administrator (their setup creates cluster-scoped objects), and to reclaim retained lab volumes |

On a cluster other than CRC, provide kubeconfigs instead of passwords: `ACADEMY_KUBECONFIG_LEARNER` and
`ACADEMY_KUBECONFIG_ADMIN`, and set `ACADEMY_API_SERVER`. The reader identity is created by the academy from the
Connections page (it needs the admin identity once); importing an external reader kubeconfig
(`ACADEMY_KUBECONFIG_READER`) is read by the configuration but has no connect path yet, so do not rely on it.

Each lab checks its requirements first (preflight) and says why it cannot run on this cluster when it cannot. Everything
a lab creates is recorded in a local cleanup ledger (`data/ledger.db`) with its UID; cleanup deletes only those exact
objects, verifies with the API server, resumes after a restart, and reports anything it cannot remove (finalizers, or
volumes kept by a `reclaimPolicy: Retain` StorageClass) on the Connections page. `.venv/bin/python scripts/volumes.py list` shows the
volumes the ledger recorded and `.venv/bin/python scripts/volumes.py reclaim --yes` (admin, same cluster) reclaims only those, with a
conditional request that fails if the volume changed. Projects that look like the academy's but are not in the ledger
are reported and never touched; you can adopt one explicitly on the Connections page by typing its name.

## Configuration reference

| Variable | Default | Meaning |
|---|---|---|
| `ACADEMY_CLUSTER` | `auto` | `off` disables every cluster feature (practice mode) |
| `ACADEMY_ALLOWED_HOSTS` | (none) | extra `Host` values; `*` only allowed with `ACADEMY_CLUSTER=off` |
| `ACADEMY_PORT` | `8768` | port for `run.sh` (and `compose.yaml`: 8080) |
| `ACADEMY_API_SERVER` | `https://api.crc.testing:6443` | cluster API used to log in |
| `ACADEMY_CRC_HOME` | `~/.crc` | where CRC's generated passwords and CA are read |
| `ACADEMY_KUBECONFIG_<ID>` | (none) | existing kubeconfig for `LEARNER`, `READER` or `ADMIN` |
| `ACADEMY_DATA_DIR` | `./data` | private runtime data (kubeconfigs, lab files, volume ledger) |
| `ACADEMY_CONTENT_DIR` | `./content` | course content and recordings |
| `ACADEMY_DIST_DIR` | `./frontend/dist` | built frontend |
| `ACADEMY_SITE_URL` | (none) | static export: canonical URLs and sitemap |
| `ACADEMY_REPO_URL` | (none) | the project's GitHub repository, `https://github.com/<owner>/<repository>`: turns on "Report an issue" and "Edit this lesson" |
| `ACADEMY_REPO_BRANCH` | `main` | branch the "Edit this lesson" links open |
| `ACADEMY_BUILD_COMMIT` | (from `git`) | commit shown as the build's version when the source has no `.git` (a container build) |
| `ACADEMY_LANG` | `en` | default content language |
| `ACADEMY_OC_TIMEOUT` | `30` | seconds before an `oc` call is stopped |
| `ACADEMY_SITE_NAME` | from `frontend/product.json` | overrides the product name for the server only |
| `ACADEMY_PRIVATE_DIR` | `./data/recorder` | the recorder's own files (full experiment records, failed recordings, lock); never committed |

Recording administration lessons uses further variables (`ACADEMY_ADMIN_*`, `ACADEMY_RECOVERY_KUBECONFIG`), read by
`scripts/record.py` (maintainers only); local authoring uses `ACADEMY_AUTHORING*` ([AUTHORING.md](AUTHORING.md)).

## Upgrading

- Static site: rebuild, export, publish. Learners' progress lives in their browsers and is kept.
- Container: build a new image and deploy it by digest; roll back by deploying the previous digest.
- Local: pull, then refresh the dependencies and rebuild before restarting:
  `uv pip install --python .venv/bin/python -r requirements.txt && (cd frontend && npm ci && npm run build) && ./stop.sh && ./run.sh`
  (`run.sh` alone rebuilds the frontend when its sources changed, but does not reinstall dependencies).

## Uninstalling

- Local cluster mode: clean up each lab from its page (or delete `academy-*` projects you no longer need), then as
  admin `oc delete clusterrolebinding academy-reader && oc delete project academy-system`.
- Manifests: `oc delete -k deploy/kubernetes`.

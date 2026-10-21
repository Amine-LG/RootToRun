# Root to Run on Windows

Root to Run is developed on Linux, and its development tools work on Windows too. This page gives the PowerShell
commands where they differ from the Linux ones in the [README](../README.md) and [CONTRIBUTING.md](../CONTRIBUTING.md).

Four different things, which need different setups:

| You want to | You need | Checked on Windows |
|---|---|---|
| Learn with the published website | a browser, nothing else | (any browser) |
| [Run the website on your PC](#run-the-website-locally) | Git, Python 3.12 with uv, Node.js 22.12 or newer | yes, in CI on every pull request |
| [Run the development tools and tests](#run-the-tests) | the same | yes, in CI on every pull request |
| [Practise on an OpenShift cluster](#use-your-own-openshift-cluster) | `oc` and a cluster you are allowed to use | not tested on Windows |
| [Create a cluster on your PC with OpenShift Local](#optional-openshift-local) | Windows 11 (not Home), 4 physical cores, 10.5 GB of free memory | not tested by the project |

You never need a cluster, or OpenShift Local, to use the website: every lesson works with recorded outputs.

"Yes, in CI" means that the `windows` job of [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs the
commands below on a GitHub-hosted Windows runner (Windows Server): in PowerShell 7, and the local server also in
Windows PowerShell 5.1, the version Windows includes. Every command works in both. Windows 10 and 11 desktops are not
tested separately.

## Install the tools

Use the installers from each project, or `winget`:

```powershell
winget install --id Git.Git -e
winget install --id astral-sh.uv -e
winget install --id OpenJS.NodeJS.LTS -e
```

Open a new PowerShell window afterwards, so that the new commands are on `PATH`. `uv` installs Python 3.12 itself
in the next step. (The CI runner has these tools preinstalled: these three commands are not run in CI.)

## Get the code and its environment

```powershell
git clone https://github.com/Amine-LG/RootToRun.git
cd RootToRun
uv venv .venv --python 3.12
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt
```

Windows puts the environment's Python at `.venv\Scripts\python.exe`, where Linux and macOS use `.venv/bin/python`.
Use it directly, as below: there is no need to activate the environment. For the website alone,
`requirements.txt` is enough; `requirements-dev.txt` adds the test tools.

The repository's `.gitattributes` keeps every text file with LF line endings, on Windows too. Editors such as
VS Code handle them; do not convert files to CRLF.

## Run the website locally

```powershell
.venv\Scripts\python.exe scripts\serve.py --practice
```

Then open http://127.0.0.1:8768. The first start installs the frontend's packages and builds it (a few minutes);
later starts rebuild it only when its sources changed. `--practice` turns every cluster feature off: the whole course
with its recorded outputs. Stop it with Ctrl+C. Another port: `--port 9000`.

On Linux and macOS, `./run.sh` and `./stop.sh` do the same in the background; `scripts/serve.py` works there too.

To work on the frontend with hot reload, keep the server running and start Vite in a second window
(`cd frontend; npm run dev`, then http://127.0.0.1:5175; it proxies the API to port 8768).

## Run the tests

The checks [CONTRIBUTING.md](../CONTRIBUTING.md) asks for before a pull request, in PowerShell:

```powershell
.venv\Scripts\python.exe scripts\check_content.py
.venv\Scripts\python.exe -m pytest tests --ignore=tests/e2e
.venv\Scripts\python.exe scripts\teach_lint.py
.venv\Scripts\python.exe scripts\slugs.py --check
.venv\Scripts\python.exe scripts\public_scan.py
cd frontend; npm ci; npm test; npm run build; cd ..
.venv\Scripts\python.exe scripts\export_static.py
.venv\Scripts\python.exe -m playwright install firefox
.venv\Scripts\python.exe -m pytest tests/e2e
```

The last command runs the browser tests against the static site exported by the command before it. On Windows, CI
runs a fifth of them (`--shard 1/5`); Linux CI runs all of them, against the production image.

A few tests are skipped on Windows, with the reason shown by `pytest -rs`: those of the Linux-only tools below, and
the frontend tests that compare displayed commands with the real `bash`. Checks of Unix file permissions (mode 600)
have nothing to check there. CI also checks that the site exported on Windows is byte-for-byte the one exported on
Linux.

If PowerShell says that running scripts is disabled when you type `npm`, either type `npm.cmd` instead, or allow
local scripts for your account once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## What stays Linux-only

| Part | Why | On Windows |
|---|---|---|
| `run.sh`, `stop.sh`, `scripts/practice-server.sh` | Bash scripts that run the server in the background | `scripts\serve.py`, in the foreground |
| The production image (`Containerfile`), `scripts/smoke_image.sh` | a Linux container image, tested with a Bash script | CI builds and tests it on Linux; Podman Desktop or Docker Desktop (WSL 2) can build it, untested |
| `scripts/record.py` (recording lessons) | runs the lessons' commands in Bash, on Linux | maintainers record on Linux |
| `scripts/grading_oracle.py` | runs `oc` in a bubblewrap sandbox | Linux only; CI skips it too |

## Use your own OpenShift cluster

Not tested on Windows. Root to Run's cluster features use the `oc` client and kubeconfig files, which exist for
Windows, but no Windows machine has run the labs against a cluster.

1. Install `oc` for Windows: the cluster's web console offers it (**?** → **Command line tools**), as does
   OpenShift Local (below). Put `oc.exe` on `PATH` and check with `oc version --client`.
2. Follow a lesson's commands in a Linux shell if you can. The lessons were recorded in Bash on Linux: `oc` commands
   alone work the same in PowerShell, but pipes to `grep`, `$(...)`, `export` and here-documents do not. WSL 2
   (`wsl --install`), Git Bash or the web console's terminal run them as written. The Linux course needs a Linux
   system anyway, for example WSL 2 or a virtual machine.
3. For the live labs, start the server without `--practice` (`.venv\Scripts\python.exe scripts\serve.py`), then
   open **My cluster → Connections** and follow [docs/INSTALL.md](INSTALL.md#local-cluster-mode). Use a disposable
   cluster, never a production one.

## Optional: OpenShift Local

OpenShift Local (CRC) runs a single-node OpenShift cluster in a virtual machine. On Windows it needs Windows 11, not
the Home edition, 4 physical CPU cores, 10.5 GB of free memory, 35 GB of disk, and a Red Hat account for the pull
secret ([CRC: installing](https://crc.dev/docs/installing/)). Install it from its download page, then:

```powershell
crc setup
crc start
& crc oc-env | Invoke-Expression    # puts OpenShift Local's oc on PATH for this window
crc console --credentials           # the developer and kubeadmin logins
```

Not tested by the project on Windows: the recordings were made with OpenShift Local 4.21 on Linux.

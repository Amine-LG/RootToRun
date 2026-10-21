# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub's "Report a vulnerability" (Security advisories) on this
repository, not in public issues. Include steps to reproduce and the affected version. We aim to acknowledge reports
within a few days.

## Security model in short

| Mode | Exposure | Cluster access |
|---|---|---|
| Static site, its container image (nginx and static files only), Kubernetes example | may be public | **none**: no credentials, no cluster calls |
| Local cluster mode (`./run.sh` with a reachable cluster) | **127.0.0.1 only** | yes, through a command policy |

Cluster mode is a single-user, local tool:

- Binds to 127.0.0.1 and rejects foreign `Host` headers (DNS rebinding); state-changing requests need a custom header
  (`X-Academy: 1`) and CORS is never granted (CSRF). `ACADEMY_ALLOWED_HOSTS=*` refuses to start when a cluster is
  reachable.
- No endpoint executes arbitrary commands. Commands are parsed into argv and checked against an allowlist
  (`backend/academy/policy.py`): no shells, no credential/context/kubeconfig flags, no host file paths (template files,
  `--cert`, `--from-file`, `--to` paths, `-f` outside the lab's own files), output formats limited to inline templates,
  learner writes limited to academy-owned `academy-*` projects, the reader identity is read-only and never reads
  Secrets, `oc adm` limited to read-only subcommands, Helm limited to lab charts.
- Lab cleanup deletes only projects the academy created (name prefix and description marker). Volume reclaim touches
  only volumes recorded in a ledger at cleanup time.
- Administrator credentials are used by the maintainers' local recording tool (`scripts/record.py --lessons
  --admin`), against a disposable training cluster it verifies by ID. In local cluster mode, the person running the
  server may also connect a cluster-admin identity to their own training cluster: this needs training mode to be
  approved and a typed confirmation, and it exists only in that single-user, loopback-only mode. The static site and
  every public deployment have no cluster access at all, so no visitor can reach an administrator identity. Never
  expose cluster mode on a network. Continuous integration runs on GitHub's hosted runners with a read-only token and
  has no cluster access or credentials.
- Cluster tokens and passwords never reach the browser; kubeconfigs are stored with mode 0600; child processes get a minimal
  environment; outputs are redacted for OAuth tokens and JWTs.

## Local content authoring

Authoring is off by default and requires `ACADEMY_AUTHORING=1` at server startup. Its separate bearer token is
printed in a local startup URL, consumed from the browser fragment and kept in that tab's `sessionStorage`.
Every author API call needs the token and a loopback client address. Keep the server bound to loopback,
disable proxy headers, and protect the startup log as a credential. Authoring edits course files only;
review the Git diff before proposing a pull request. Static exports force authoring off. See
[Local authoring mode](docs/AUTHORING.md#local-authoring-mode) for the workflow and limits.

## Trust boundaries you should know

- **Content is code for the recorder.** `scripts/record.py` executes lab commands (as admin when a lab says so) and
  lesson host commands through `bash`. Only record content you trust; review third-party lab YAML like code.
- **The maintainer tools are trusted tools with guards.** They run real programs with your credentials:
  - `scripts/record.py` runs lesson and lab commands from course content through `bash` with your privileges, on an
    approved training cluster only, and never adopts an existing project on its own. In administration recordings
    the `oc` it gives the administrator and recovery identities refuses options that change the connection, the
    credentials or the kubeconfig (in any spelling), but those lessons may impersonate (`--as`); the developer and
    test-user identities use the plain client. When a lesson recording is interrupted (Ctrl-C) or a step fails, the
    running command is stopped, and every rollback step and the removal of the temporary project are still
    attempted (a failing step is reported as a problem of the recording); a Ctrl-C pressed during that cleanup is
    held until it is done. Removing the private session directory, with its copies of credentials, is always
    attempted at the end; if it fails, a warning names the directory to delete. A process killed outright cleans
    up nothing. A recording killed outright, a failure while the session is
    being set up, or a cluster outage can leave its temporary project or an experiment's changes behind; a lab
    recording that fails midway leaves its projects to the cleanup ledger, which removes them at the next run. Scrubbing replaces
    known passwords, tokens, keys and machine details, not every possible secret: read recordings before
    publishing them.
  - `scripts/cluster_read.py` runs `oc` with the administrator's or the developer's credentials, only for the reads
    and dry runs it can read completely (known options only); anything else is refused. It reduces mistakes; it does
    not make arbitrary commands safe.
  - `scripts/grading_oracle.py` runs the client on command lines from course content inside a bubblewrap sandbox:
    only `/usr`, `/etc` and the client binary are visible (read-only; no home directories, `/run` or `/var`, so no
    host sockets), with a writable scratch directory and private `/tmp`, and no network. With `--server` it compares
    reads on the training cluster: the network is shared and the learner kubeconfig's directory is visible
    read-only, and only lines that `scripts/cluster_read.py` accepts as reads are run.
  - Only one recording runs at a time per recorder directory (`ACADEMY_PRIVATE_DIR`); two checkouts with different
    directories do not see each other's lock.

  Run them on pull-request content only after reading it.
- **Do not expose cluster mode** through a reverse proxy or a non-local interface.
- **Use a disposable cluster** (OpenShift Local / CRC, a test cluster). Never point the academy at production.

## Supported versions

Security fixes are made on the latest release only.

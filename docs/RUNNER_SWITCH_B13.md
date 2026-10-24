# B1.3: operator switch on the existing site

Related: [Issue #31](https://github.com/hungdo2006/battlecode_MIT_Group_8/issues/31).
This is an in-place preparation, not another VM. Codex has not run these commands
on EC2. The owner must separately approve and execute the maintenance window.
Do not merge/deploy automatically. PR #30 remains separate staging preparation.

## Live facts and gates

Owner supplied, **not verified again on EC2**, 2026-10-24:

- Project `neon-arena`; explicit order `compose.yaml`, private
  `compose.override.yaml`, `compose.public.yaml`.
- Expected volumes `neon-arena_arena_data`, `neon-arena_arena_uploads`,
  `neon-arena_arena_artifacts`, `neon-arena_caddy_data`, `neon-arena_caddy_config`.
- Account-Only/player signup were used; Admin TOTP was 0 and public Admin
  password-only was 1. Capture actual effective flags; preserve them exactly.
- Public HTTPS hostname/certificate is unknown; no separately registered domain
  is confirmed. **BLOCKED** until actual origin and public trust are verified
  from the laptop. A public IP is not evidence of valid HTTPS.
- Live source/image IDs, schema, private override behavior, mounts, jobs, free
  disk and complete backup/restore are **BLOCKED** pending operator evidence.

Do not infer these from local QA, SSH into AWS, provision resources, overwrite
`.env`/private override or use the fresh-staging Compose file for this site.

## Architecture and safety

`backend.runner_control` owns mode normalization, persistent admission intent,
fresh process acknowledgement and audit. `sandbox`/`local_sandbox` mean local;
`remote_sandbox` means outbound PC relay. Mode changes require Arena restart.

Drain closes new compilation/match admission. Existing matches finish and
dispatch reconciliation continues. Any upload, dispatch claim, match or pending
Controller cleanup refuses cutover **before any service stop**. Drain refusal
leaves admission closed: let work finish and retry, or explicitly resume the
same ready mode. Intent survives crashes. Uncertain jobs never get a fake win.

`scripts.runner_switch` is a separate privileged local Docker actuator. It
captures the **full resolved model**, not a merged overlay. Remote has only
Arena/Caddy, no local Controller URL/token/dependency, no published Arena port or
Docker socket. It retains original public ingress, account/signup/password-only
settings, image/schema, data/uploads/Caddy mounts. Local artifact volume remains
in the rollback model/project; Compose dropping an unused declaration does not
delete it. No tool removes volumes, prunes, runs down or contacts SSH/AWS.

Images are pinned to immutable IDs. File/key/bind checksums, Engine identity,
actual mounts and a complete cold backup plus restore drill gate switching.
Unknown extra services require review. Literal dollars are decoded from
Compose's output escaping and re-encoded once, with real round-trip validation.

Future Admin UI can reuse decision/readiness/status and request maintenance;
a separately authenticated operator process owns deployment and its audit.
This phase adds no public switch API, browser SSH/Docker, hot swap, runtime
automatic fallback, arbitrary PC enrollment, extra workers or capacity above 2.

## Protected preparation (operator, on Docker host)

Use the reviewed checkout, Python 3.13 and Docker Compose supporting JSON config.
Remote TCP/SSH Docker contexts are refused. Generated files contain secrets:
store outside Git or under `.runner-switch/` (gitignored/Docker-excluded), use
Linux `umask 077` or restrict Windows NTFS ACL to the operator. Do not share raw
config, inspect output, logs, env, receipts or backups in chat/GitHub.

Record private source SHA, image IDs, namespace, actual mounted volume ownership,
effective auth/signup flags, origin/domain, schema and active/future Official and
Scrimmage jobs. Preserve current password-only policy; strengthening MFA needs
separate approval. Stop on any unexpected behavior. Baseline schema is 20.

Generate a random shared machine key into a protected file without printing it;
transfer by an approved private channel. It must differ from Controller token.

```sh
umask 077
python -m scripts.runner_switch prepare \
  --compose compose.yaml --compose compose.override.yaml --compose compose.public.yaml \
  --env-file .env --project neon-arena \
  --key-file /secure/neon-remote-machine.key \
  --directory .runner-switch/local-to-pc
```

`prepare` reads config/images, creates private files, prints project/volume names
and remote service names only. It never stops/starts services. Keep the bundle
on that same Engine; both modes use the same Arena image. Code upgrade is a
separate maintenance operation.

### First install when the deployed image predates this protocol

`status`/switch **must refuse** an older image without admission acknowledgement.
Do not bypass it. An owner-executed one-time cold upgrade to the reviewed
switch-aware image is required before normal switching.

Schedule downtime, inspect/cancel/reschedule jobs through authorized application
workflows, close ingress and ensure no work remains. Stop only this site's
Arena/Controller/Caddy using original explicit Compose order. Take a complete
cold backup below against the original pinned bundle **before upgrade**, and
verify recovery to its image/schema on isolated new volumes. Manual cold stop
replaces the unavailable drain protocol; no automated safe drain of old code is
claimed. Retain exact original files and pre-upgrade images/snapshot.

Deploy the reviewed switch-aware image in local mode on original volumes;
validate accounts/settings, admission protocol and local bot execution. Prepare
a **new** bundle and a new cold backup/drill for that image before switching.
This PR adds no schema migration. Never blindly downgrade a later changed schema.
Old bots without artifact-store attestation need source re-upload after the
first upgrade; historical results/replays are retained.

## Complete cold backup + restore drill

For a switch-aware site:

```sh
python -m scripts.runner_switch status --directory .runner-switch/local-to-pc
python -m scripts.runner_switch preflight --target remote --directory .runner-switch/local-to-pc
python -m scripts.runner_switch drain --directory .runner-switch/local-to-pc
```

If busy, stop nothing. Retry after work finishes. Stop only these services with
the **generated full local model** (never add the old overlay to it):

```sh
docker compose --env-file .runner-switch/local-to-pc/empty.env -p neon-arena \
  -f .runner-switch/local-to-pc/local.json stop arena controller gateway
python -m scripts.runner_site_backup backup \
  --directory .runner-switch/local-to-pc --backup-directory /secure/b13-cold-unique
python -m scripts.runner_site_backup drill \
  --directory .runner-switch/local-to-pc --backup-directory /secure/b13-cold-unique
python -m scripts.runner_site_backup verify \
  --directory .runner-switch/local-to-pc --backup-directory /secure/b13-cold-unique
```

The helper refuses running writers on all five volumes. Missing historical
artifact images fail backup even if the current image exists. Recover those
exact images; never discard references or call partial files successful.

Complete bundle: core snapshot, all referenced image IDs/archive, Caddy
data/config snapshot and Caddy image archive, exact private input/generated
configs/env/key/bind files, hashes and `complete.json`. `drill` restores into
**five new volumes**, checks files/archive hashes, SQLite integrity/foreign keys
and schema 20, and records `drill.json`.
No services start and no originals are overwritten/deleted. Retain drill volumes.
This automatic drill verifies file restore; before live approval, operator must
also start a network-isolated clone with a unique Controller namespace, check
SQLite integrity/schema, accounts, old replay and a real match. Invalidate
restored sessions before exposing a clone.

Backups contain private keys, credentials and account/session data: restrict ACL,
encrypt and retain a verified off-host copy. Check disk space for image archives.
Restart the drained local site with the same full model (`up -d --no-build`),
resume only when ready. Take a new consistent backup if cutover is postponed.

## Windows PC preparation

Use Docker Desktop **Linux containers**, same reviewed commit, AC/no sleep or
hibernation, stable outbound Internet and sufficient memory/CPU/disk. No router
port forwarding or inbound Windows port is needed. Keep Docker/socket local.

Create a protected worker env outside Git, substituting privately generated
values below; never print or paste the real values:

```dotenv
ARENA_REMOTE_SERVER_URL=https://THE-VERIFIED-PUBLIC-HOSTNAME
ARENA_REMOTE_RUNNER_KEY=THE-NEW-SHARED-MACHINE-KEY
ARENA_RUNNER_TOKEN=A-DIFFERENT-PC-ONLY-RANDOM-TOKEN-32-PLUS-CHARACTERS
SANDBOX_NAMESPACE=neon-b1-worker
DOCKER_SOCKET_GID=0
```

The PC-only token never goes into new Cloud config. Validate URL from Windows
using normal trust; no `-k`, disabled hostname checks, QA CA or trust-store edit.

```powershell
docker context show
docker info --format '{{.OSType}}'
docker compose --env-file C:\Secure\neon-worker.env -p neon-b1-worker -f compose.remote-worker.yaml config -q
docker compose --env-file C:\Secure\neon-worker.env -p neon-b1-worker -f compose.remote-worker.yaml build
docker compose --env-file C:\Secure\neon-worker.env -p neon-b1-worker -f compose.remote-worker.yaml up -d --no-build
```

Controller stays private; agent has no socket. Until Cloud switches, local mode
has no remote routes and agent retries are expected. Keep PC artifacts. Do not
start another worker using this key. Record toolchain/store identity privately.

## Switch and acceptance

On the Docker host, after verified backup/drill and PC preparation:

```sh
python -m scripts.runner_switch switch --target remote \
  --directory .runner-switch/local-to-pc \
  --backup-directory /secure/b13-cold-unique --execute-project neon-arena
python -m scripts.runner_switch status --directory .runner-switch/local-to-pc
```

The tool checks system-trusted public TLS before stopping, drains, stops Arena
and Controller, starts only remote Arena without build/pull, waits for Worker
readiness then resumes. Caddy keeps its original ingress/volumes. Browser can
see 502/503 during restart/wait. Failed target while admission is closed attempts
pinned source rollback. Failed rollback keeps admission closed for intervention.
Audit is private `operations.jsonl` and data `.runner-control/audit.jsonl`.
Once resume is attempted, lost acknowledgement or failed audit requires manual
status inspection and never triggers automatic rollback of possibly active jobs.

`/api/health` reports actual `remote-outbound` transport. Operator `status` shows
mode, admission, process ID/time, readiness, jobs, upload/dispatch and cleanup,
even while public health is 503. No disconnected Worker triggers local fallback.

Real Internet acceptance (operator; not yet performed):

1. Check unchanged accounts/login/signup/Admin flags and old result/replay hashes.
2. Re-upload/select Python/C++/Java on PC. Same image ID does not prove the
   artifact exists on that store; mismatches become `needs_rebuild`.
3. Run two concurrent Official matches and a queued third, verify replay/results,
   tournament standings and unchanged cap 2.
4. Attempt switch while busy: refuse before stopping. Explicit same-mode resume
   lets queued work finish, or leave drained until maintenance.
5. Controlled agent/network stop and reconnect: uncertain active matches become
   INTERRUPTED without winner; verify fresh compile/Official after recovery.

## Return to local / rollback

```sh
python -m scripts.runner_switch switch --target local \
  --directory .runner-switch/local-to-pc \
  --backup-directory /secure/b13-cold-unique --execute-project neon-arena
```

Same switch-aware image/schema needs no data restore: Cloud kept accounts,
uploads, results and replay. Original local artifact volume reattaches. Old local
artifacts with matching store/image become usable; PC compilations need source
re-upload locally. Frozen requests on the other store may block; resolve through
official workflow, never edit historical slots/results. Stop PC worker after
rollback with its explicit Compose/env/project `stop`; retain its artifacts.

If readiness rollback fails, keep admission closed. Inspect private logs, exact
image/mounts and leases. Restore original pinned config/images with compatible
volumes, or verified compatible cold snapshot into **new** volumes. Validate
before ingress. Never `down -v`, prune, delete DB, overwrite private `.env`, or
downgrade unknown schema.

## Local checks

```powershell
.\.venv\Scripts\python.exe -m pytest tests controller_tests -ra --tb=short
.\.venv\Scripts\python.exe scripts/check_b13_compose_config.py
.\.venv\Scripts\python.exe scripts/check_b13_switch_docker.py --build
.\.venv\Scripts\python.exe scripts/check_b1_real_world_qa.py --evidence .qa-evidence/b13-full-b1
```

The switch rehearsal uses unique QA projects, private Docker HTTPS and dummy
accounts, tests actual config, complete backup/file restore, failed-target
rollback, busy refusal, two-way switch, artifact mismatch, retained Official
replay/results/standings. It stops only its QA services and **retains** its QA
volumes/backups. Evidence is ignored. Internal CA is trusted only in QA
containers by the harness; operator CLI has no TLS-bypass flag. This does not
prove two physical hosts, public TLS, live EC2 configuration or Internet stability.

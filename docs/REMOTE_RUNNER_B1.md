# B1 — Remote Sandbox Runner (single PC, outbound-only)

> **Draft / pre-production milestone.** Independent from the offline results
> import work in PR #24. These instructions are for **fresh staging environments
> with dummy users and bots**, not for the currently running AWS instance.
> Do not merge, migrate or deploy production until real Docker end-to-end QA.

## Architecture and security boundaries

```text
                  HTTPS (verified hostname)
  Students ---> [Caddy / Arena cloud staging] <--- outbound HTTPS --- [PC agent]
                    |     ^                                      |
              SQLite/replays |                              private network
                (cloud)      + RPC responses                      |
                                                                  v
                                                        [Sandbox Controller]
                                                          Docker socket
                                                                  |
                                                         [bot containers]
                                                       no network / non-root
```

- Cloud Arena executes the **existing** `SandboxRunner` / Official / Scrimmage
  control path with `ARENA_RUNNER=remote_sandbox`. It starts without a PC
  but reports `/api/health` as unavailable until the remote Controller's
  epoch/lease/health is confirmed. There is **no legacy/local execution fallback**.
- The PC runs `compose.remote-worker.yaml`: an isolated private Controller,
  pinned bot toolchain image and a tiny outbound HTTPS agent. **Only the
  Controller has a Docker socket**; no service publishes port 9000.
- Agent connects to cloud `/api/remote-runner/*` over HTTPS with a separate
  machine secret, receives allowlisted sandbox protocol commands and returns
  bounded JSON results. It never receives an SSH session, arbitrary URL or
  shell command from cloud.
- The PC-only `ARENA_RUNNER_TOKEN` authenticates Controller operations.
  **Never put this token on the cloud server.** Separately generate
  `ARENA_REMOTE_RUNNER_KEY` (at least 32 random characters) and configure
  it on both cloud and PC. Never log or commit either credential.
- One worker session at a time (new sessions accepted only after stale/disconnect).
  Each request has a random ID; duplicate, late or forged responses are rejected.
  After disconnect, cloud rejects new work and existing requests time out or
  fail; Official/Scrimmage recovery remains responsible for marking work
  interrupted, never for automatically awarding a victory.
- Existing maximum of **two matches at once remains unchanged**.
  No multi-runner dispatch, autoscaling, distributed queue or B2 scheduler.
- The cloud persists match history, scores and replay on its own storage, **not
  in the PC Docker volume**. The PC keeps compiled artifact archives; losing or
  replacing the PC/controller image can make historic artifacts incompatible,
  requiring players to reupload/recompile sources before a new match.

## One-laptop PC worker Docker smoke (before cloud staging)

The Windows/Linux unit tests exercise the RPC queue and machine authentication,
but do not prove that the **PC Docker stack** launches or executes uploaded
Python code. As a separate, safe prerequisite to full cloud HTTPS E2E, run on
Docker Desktop with **Linux containers**:

```powershell
.\.venv\Scripts\python.exe scripts/check_remote_worker_docker.py --build
```

This creates a fresh `neon-b1-worker-qa-<random>` Compose project, builds
only **QA-tagged** images, verifies the Controller's private network and
Docker socket separation, and calls the Controller through the **real PC agent**
to compile a Python bot in Docker, start it and obtain a `wait` action.

The environment has a **deliberately disconnected example HTTPS origin**
(`https://qa-disconnected.invalid`). The agent background service will not
connect to any cloud or AWS instance during this smoke. A successful run ends
with `"b1_worker_smoke": "PASS"`, then stops the QA project and deletes only
volumes whose owner labels and project prefixes match.

**What PASS does not prove:** cloud machine-auth HTTP endpoints, agent long
polling over real TLS, remote result/replay delivery, Official Match recovery
or PC-to-cloud network loss. These require the subsequent separate cloud + PC
HTTPS staging exercise; do not merge/deploy B1 based only on this smoke.

## One-laptop cloud ↔ PC HTTPS end-to-end rehearsal

After the local PC worker smoke passes, test the entire B1 path **without AWS,
without buying a second PC, and without installing any certificate on Windows**:

\`\`\`powershell
cd "$HOME\neon-arena-b1-qa"
git pull --ff-only origin feature/b1-outbound-remote-runner-20261023
.\.venv\Scripts\python.exe scripts/check_b1_cloud_tls_docker.py --build
\`\`\`

The new \`scripts/check_b1_cloud_tls_docker.py\` provisions **two disposable
Compose projects** with separate data/volumes: a remote-only Arena backed by
Caddy and a PC agent + Controller. Both projects can communicate **only**
through a dedicated Docker QA transport network:

- \`https://arena-qa.test\` is a Docker network alias, **not** a public DNS
  record and has no host-published ports.
- Caddy's local QA CA issues the TLS certificate. Its root is copied into
  a private temporary folder under the current user's home directory, then
  bind-mounted read-only into the agent as \`SSL_CERT_FILE\`. HTTPS hostname
  and certificate validation remain **enabled**. This ephemeral CA is not
  installed in the Windows certificate store.
- Admin password-only mode is **explicitly enabled only in this sealed local
  test** to seed synthetic users; actual public/staging deployments must
  require Admin TOTP. No operator or production keys are copied.
- The script provisions real Admin/Player/Teams, uploads two bot sources and
  compiles them on the off-host Controller, runs an Official Match, checks
  replay, then stops the agent to require fail-closed health. It restarts
  the agent and checks that the remote lease becomes healthy again.
- Cleanup stops **only the two random QA projects** and removes their
  label-verified QA volumes. Never use Docker system prune or a production
  project name for this test.

\`"b1_https_e2e": "PASS"\`, \`"agent_disconnect": "PASS"\` and
\`"agent_reconnect": "PASS"\` mean the Docker Desktop rehearsal passed. They
**do not yet prove** public CA validation, a physically separate PC over
the school/WAN, performance at sustained two-match load, full outage
recovery during an in-flight Official Match, or AWS production suitability.

The first run builds QA-tagged images; reuse the same checkout with no
\`--build\` on later runs unless backend/worker code or dependencies changed.

## Cloud staging — fresh isolated VM and domain required

1. Prepare **a different staging VM / DNS name** with ports 80 and 443 available,
   valid Caddy HTTPS certificates and a clean project volume. Never overlay
   `compose.remote-cloud.staging.yaml` on `compose.yaml`, `compose.public.yaml`
   or the active AWS project's volumes. Its default project name is
   `neon-b1-cloud-staging`.
2. Copy `.env.example` to a private `.env`. Set at least
   `ARENA_PUBLIC_DOMAIN`, a 48+ character `ARENA_PROXY_SECRET`, and a
   separate 32+ character `ARENA_REMOTE_RUNNER_KEY`. The cloud must not contain
   `ARENA_RUNNER_TOKEN` or the PC Docker credentials.
3. On this new staging project, initialize/migrate the **staging** Account
   database and provision a test Admin using `backend.admin_cli` while the
   web service is stopped. Follow `docs/OPERATIONS.md`; this repo deliberately
   never auto-migrates an existing Account DB. Use test-only accounts, MFA and
   two new Teams. Account-Only, public HTTPS and Admin MFA remain enabled.
4. Bring up the staging services with:

   ```sh
   docker compose -f compose.remote-cloud.staging.yaml config
   docker compose -f compose.remote-cloud.staging.yaml up -d --build
   ```

   The server may appear unhealthy before a PC registers; this is a safe
   fail-closed state. Do not change the healthcheck to report a fake success.

## PC / laptop — Linux container Docker Engine or Docker Desktop

1. Checkout the **same B1 revision** as cloud on the PC. Create its private
   `.env`. Set `ARENA_RUNNER_TOKEN` (a unique random 32+ character PC-only
   token), `ARENA_REMOTE_RUNNER_KEY` (same shared machine secret as staging)
   and `ARENA_REMOTE_SERVER_URL=https://<staging-domain>` (HTTPS, valid
   certificate, origin only; no path). Set `DOCKER_SOCKET_GID` if needed for
   Docker Engine socket permissions on Linux.
2. Run **only** the PC stack on the PC:

   ```sh
   docker compose -f compose.remote-worker.yaml config
   docker compose -f compose.remote-worker.yaml up -d --build --wait
   docker compose -f compose.remote-worker.yaml ps
   ```

3. Verify `https://<staging-domain>/api/health` returns a healthy sandbox
   runner with `transport=remote-outbound`. Use staging Admin to upload
   new Python/C++/Java bot sources and run two real Official matches. Verify
   completion, matched replay and persisted standings after a restart.
4. With two matches running, disconnect PC outbound networking **in staging
   only**. No new matches may dispatch; active matches must be interrupted
   consistently, without a fabricated winner. Reconnect the agent and verify
   the Controller lease is regained and new submissions work. Re-upload bot
   source when Controller image identity changes.
5. Test the wrong machine secret, a second competing PC, old/replayed result
   IDs, delayed job replies, restart/reconnect, CPU/RAM consumption and
   backup/restore of the cloud data volumes. Do not inspect/log secrets.

## CI and release gate

```sh
python -m pytest tests/test_remote_relay.py tests/test_remote_runner_http.py tests/test_remote_runner_agent.py -ra
python -m pytest tests controller_tests -ra
docker compose -f compose.remote-worker.yaml config
docker compose -f compose.remote-cloud.staging.yaml config
```

Environment-independent unit/integration tests and GitHub Actions cannot
establish two-host TLS, real Docker execution, LAN isolation, replay fidelity
or recovery after a physical network outage. Record PASS/FAIL/BLOCKED per
criterion, source SHA, image IDs, environment, redacted logs and observations.
**Do not mark the PR ready or deploy to the existing AWS instance** until
these staging acceptance checks and a production backup/rollback plan pass.

## Deliberate limitations

The PC must have a working outbound Internet connection to the cloud for B1;
this is **not** the air-gapped Exam LAN mode from Phase A. When the school has
no Internet, keep the local offline exam deployment and transfer signed results
later via Phase A. B1 does not increase concurrency or replace that workflow.

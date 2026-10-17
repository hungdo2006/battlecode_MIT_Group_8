# NEON ARENA — One-click local QA (Windows)

This is a **local-only**, Docker-backed preview of the **merged main branch**.
It does not touch the default `neon-arena` Compose project, its volumes,
an AWS instance, or the unfinished Phase 4.2D PR.

## First use

1. Install/start Docker Desktop and select **Linux containers**.
2. In the repository folder, double-click **Start-NEON-ARENA-QA.bat**.
3. The launcher will attempt `git pull --ff-only origin main` only while on a
   clean `main` checkout. Dirty tracked files are never overwritten. Network
   pull failures leave the local checkout unchanged.
4. The first launch builds isolated Docker images, creates a fresh QA database
   in dedicated volumes, and prompts once for the password of `qa.admin`.
   Password input is hidden and is not saved to a file.
5. The browser opens **http://127.0.0.1:18042**.

Later, double-click the same Start file again. Existing accounts, uploaded bots,
and data are retained across restarts. `Stop-NEON-ARENA-QA.bat` shuts down
only the local QA project, **without** deleting its volumes.

## Scope and safety

- Project: `neon-arena-click-qa`; bind: `127.0.0.1:18042`; Account-Only enabled.
- Custom QA image tags, including the bot image used by the isolated controller,
  avoid replacing the default `neon-arena:4.0` image tags.
- Local configuration and the cryptographic runner token are saved under
  `%LOCALAPPDATA%\NEON_ARENA\click-qa\` (outside the repository).
- The only automatic database migration is initial creation **when no database
  file exists**. An existing outdated/invalid schema results in a safe stop
  with a readable error; the launcher never upgrades an existing database.
- The script does not create Player accounts. After signing in as Admin, issue
  account invitations in the UI/API and activate them as Players.
- Do not expose port 18042 to the Internet. The opt-in HTTP authentication setting
  is intended for local QA only.
- Changes from an unreviewed feature branch are **not** launched by this script.
  Return to `main` manually; the launcher never force-switches branches.
- First startup needs network access to Git/Docker registries if images are absent.

## Troubleshooting

- Wrong branch: run `git switch main` in PowerShell; save your current changes
  first if Git blocks the switch.
- Docker CLI missing/unhealthy: start Docker Desktop, Linux containers.
- Port already in use: stop the other service using port 18042. The launcher
  deliberately does not pick a new port silently, because Origin is pinned.
- Failed build/health: use Docker Desktop's container logs for
  `neon-arena-click-qa`, or run PowerShell:

  `docker compose -p neon-arena-click-qa --env-file "$env:LOCALAPPDATA\NEON_ARENA\click-qa\qa.env" -f compose.yaml -f "$env:LOCALAPPDATA\NEON_ARENA\click-qa\compose.qa.yaml" logs --tail=100 arena controller`

- Forgot Admin password: the script deliberately does not reset or print it.
  Follow the approved account recovery procedure; do not delete volumes to
  circumvent credentials.
- To deliberately discard QA data, follow a manual reviewed reset process.
  The one-click launcher has **no** destructive volume-delete operation.

## For reviewers

Script entry: `scripts/start_local_qa.ps1`. It is intentionally small enough
to audit before running. The BAT files execute that known local script once
with a process-scoped PowerShell execution policy override. No remote script is
downloaded and executed. CI/QA should validate both fresh and repeated start,
branch mismatch, existing schema mismatch, Docker Desktop and fail-closed paths.

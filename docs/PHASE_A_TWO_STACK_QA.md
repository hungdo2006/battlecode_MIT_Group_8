# Phase A: real Docker Offline → Online acceptance on one laptop

This is a **disposable, local functional rehearsal**, not the offline school
network deployment. Run it only on a workstation with Docker Desktop / Linux
containers, never over SSH on the live AWS host. It creates fresh synthetic
Admin/Player accounts, two distinct Compose projects and Docker volumes.

## Run

With Python 3.13, development requirements installed and Docker Desktop ready:

```powershell
.\.venv\Scripts\python.exe scripts/check_offline_online_docker.py --build
```

Reusing the QA images already built on the same checkout:

```powershell
.\.venv\Scripts\python.exe scripts/check_offline_online_docker.py
```

Both commands use QA-specific image tags (not the normal `neon-arena:4.0`
production image). `--build` builds all three QA images; otherwise the
script requires the QA tags to exist. The Docker Compose subproject names have
the pattern `neon-phase-a-{off,on}-XXXXXXXXXX` and bind **only**
`127.0.0.1` on separate random host ports.

## Verifications

1. Bootstrap separate SQLite instances and in-memory QA credentials; require
   Account-Only authentication with localhost-only HTTP as a deliberate test
   exception. The **real Exam configuration requires managed HTTPS + Admin
   TOTP**, and is not used here.
2. Compile two Python bots through the real Docker Sandbox, register two active
   Teams, select an Active Bot for each Team.
3. Start a real two-Team Single Elimination Tournament. Schedule the Official
   match, wait for its actual result and verify replay frames. No synthetic
   terminal status is injected into SQLite.
4. Export HMAC-SHA256 result package from the completed event, verify that
   publicly exported fields contain no bot source/artifact identifiers.
5. Log into the **other Compose project** as Admin; check unsigned/tampered
   results and missing CSRF are denied, preview has zero publication side
   effects, publish, reimport idempotently, inspect anonymous public standings
   and /results, and assert existing online Team/public authority unchanged.
6. Restart the online Arena and compare publication bytes after restart.
   Reports `"phase_a": "PASS"` only when every assertion succeeds.

Each project has its own private Controller network, Sandbox namespace,
instance-scoped Controller bearer token and separately named data/uploads/
artifacts volumes. Signing key is randomly generated *once* for the test and
shared only between the two ephemeral Arena instances. Credentials and signing
key are never committed or intentionally printed. The script cleans up only
verified QA-owned volumes, and stops both QA projects on error.

**Not covered:** HTTPS/TOTP/CA trust, physical LAN/WAN air-gap, two host/PC
deployment, disaster recovery of Caddy volumes, external DNS/IPv6/proxy/phone
hotspots, Internet-hosted AWS staging, user-interface clicks and production
database migration. Keep these release gates separate and do not update AWS
based only on this local PASS.

If the run fails, paste the traceback and only the last redacted console
lines. Do not share any private `.env`, Docker inspect dumps, raw result
packages containing non-test teams, cookies, access tokens or signing keys.

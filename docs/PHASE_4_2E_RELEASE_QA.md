# NEON ARENA — Phase 4.2E Final System QA / Release Gate

**Status:** QA preparation and independent acceptance **in progress**. This page is a checklist, not evidence that the product has passed. Phase 4.2D was merged via PR #7; Phase 4.2E evaluates the **current merge candidate**, including later Tournament, Leaderboard and result-correction commits.

## Objective and immutable identity

Before every test, record the exact `git rev-parse HEAD`, the branch and the base `main` SHA in the QA report. Do not transplant a PASS from an older SHA. If code, lock/config, migration or CI logic changes, rerun affected checks and the full baseline. A report without executable evidence is **INCOMPLETE**.

Scope: Account-Only Admin/Player; account activation and session lifecycle; Team/Captain/Active Bot; submissions and sandbox compilation; Official Match D1–D3; live and archived replay; **Legacy** games/tournaments/leaderboards; recently added player form statistics and organizer result corrections; isolation/security; backup and restore; rate-limit and network resilience.

This is **not** public AWS deployment authorization. Phase 4.3 requires a separate threat model, networking and TLS review, cost review and explicit go-live approval.

## Safety and QA isolation

- Use a clean detached checkout on the **exact target SHA**. Do not alter application source during independent QA. Separate tests and logs from repository contents.
- All migrations and fault injections use **fresh, disposable** SQLite data and **owned** Docker projects, networks, image tags and volumes. Never reuse the older, unreleased D1 SQLite v5 test databases.
- Bind QA HTTP ports to `127.0.0.1`; use randomly generated credentials/tokens. Never point scripts at a live service, AWS volume, production database, public domain or normal Compose project.
- The existing `scripts/check_docker.py --build --browser` uses a random Compose project and label-verified QA volume cleanup, but it is a **Legacy** acceptance check. It does not by itself establish Account-Only Official Match readiness.
- Do not commit browser trace archives, auth cookies, session tokens, database snapshots or unredacted QA logs. Retain evidence outside version control; sanitize links before sharing.
- **Do not run `docker compose down -v` on a regular project**. Do not run live `migrate` or restore on AWS. Testing recovery requires disposable copies with a documented owner/project ID.

## Release gates

| ID | Gate | Mandatory evidence | Minimum acceptance |
| --- | --- | --- | --- |
| E01 | Full regression Windows/CRLF + Linux/LF | exact commands, exit codes, JUnit counts and skips | both full suites PASS; investigate every skip |
| E02 | Frontend contract and assets | `node --check`, `version_frontend --check`, canonical hashes | no stale fingerprint, JS parse error or drift |
| E03 | Browser Account-Only | fresh Chrome Admin, Player, activated invite and logout | login/revocation/team views/Official navigation functional; zero unhandled JS exceptions |
| E04 | Team/Captain & bot ownership | 2+ teams, invitations, membership transitions, Python/C++/Java uploads | cross-Team ownership denied; Captain Active Bot and deadlines correct |
| E05 | Official Match execution | 2 games × 3 languages on real sandbox, scheduled without Players online | frozen source/artifact/rules, automatic COMPLETED and correct Team result |
| E06 | Official replay | running replay, terminal frame, archive after restart | winner/scores/turn agree; unauthorized Team gets 404; no fake victory |
| E07 | Concurrency & crash | fault injection before/after durable claim and during execution | no duplicate execution, replay overwrite, invented winner or unsafe retry |
| E08 | Rate-limit resilience | visible idle ≥120s; 429 Replay; 429 restore/bootstrap; multi-tab | Retry-After respected; auto recovery; logout/revocation still works |
| E09 | Network/WebSocket | offline/online transitions; WS 503/1006; session revoked | bounded retry, connectivity indicator self-heals, no request storms |
| E10 | Legacy and tournament compatibility | `check_docker --build --browser` and 3 tournament formats | historical invite, multi-language matches, standings, replay and backups still work |
| E11 | Latest main features | player W/L/D/form/win-rate, tournament tie breaks, organizer result corrections | official results excluded from legacy ranks; corrections audited/authorized; Official matches non-correctable |
| E12 | Auth security | Admin/Player audience, CSRF, cookies, Host/Origin, anonymous access, revoked sessions | deny-by-default; no cross-Team private data or replay |
| E13 | Durable storage | fresh v4→v5 migration, integrity, restart, backup/restore | no lost data/artifact/replay, valid checksum, one writer |
| E14 | Operational boundaries | Admin private via VPN target, no public controller/socket, secrets, logs | no Internet exposure during QA; Phase 4.3 security checklist prepared |

A valid report must state **PASS/FAIL/INCOMPLETE for every E01–E14**. Mark unsupported test environments or missing proof **INCOMPLETE**, not PASS.

## Reusable baseline commands

Run these from a clean checkout using Python 3.13, Node 24 and the C++/Java toolchains. The CI workflow `.github/workflows/phase42e-baseline.yml` runs the baseline on hosted Windows and Linux for new PRs.

```powershell
python -m pip install -r requirements-dev.txt
python -m pip check
node --check frontend/app.js
node --check frontend/renderers.js
python scripts/version_frontend.py --check
python -m pytest tests controller_tests -ra --tb=short
git diff --check
```

Browser checker (requires separately installed `playwright` and actual Chrome):

```powershell
python -m pip install playwright
python scripts/check_account_ui.py
```

Legacy Docker/Chrome checker, only with Docker Desktop Linux containers and local test resources:

```powershell
python scripts/check_docker.py --build --browser
```

**Important:** E03–E09 and E11–E14 need additional independent browser/Docker/adversarial evidence. The automated baseline and Legacy checker alone are insufficient.

## Mandatory acceptance workflows

### Account-Only E03–E06

1. Create a clean Admin and multiple invited Players in a disposable DB. Activate accounts through supported APIs and Chrome UI.
2. Create Team A and Team B, test Captain handoff/ownership and invite/member isolation. Upload ready compiled bots in Python, C++ and Java as supported.
3. Admin schedules a Robot Battle and an OTT v2 Official Match. Freeze the selected Active Bots at deadline. Change a Captain selection after the deadline: snapshots must remain unchanged or fail closed.
4. Shut down Player/Captain browsers; demonstrate sandbox dispatch and finish independent of Player presence. Validate Team result mapping and persisted replay frames.
5. View live and completed replay as Admin, each participating Player and an outsider. Outsider must not retrieve private details or replay. Interrupted/incomplete terminal evidence must **never** produce a published winner.

### Resilience E07–E09

Use controlled isolated faults after durable claim, before JSON metadata, during sandbox execution, after replay, during startup/shutdown and with replay truncation. Repeated `recover_uncertain` must not rerun possibly executed matches. Run 2 simultaneous Official matches with a third waiting. Keep backend auth quotas enabled and demonstrate:
- Admin visible idle 120 s without normal polling hitting 429.
- Live replay receiving a real `Retry-After: 60` and sending **zero automatic requests** before the quiet window ends.
- Authenticated page reload/startup hit by 429, then auto-initializing after the backoff without a user click.
- Multi-tab shared session behavior and revocation within a documented bound.
- Browser goes offline and recovers: successful protected GET clears stale offline state. WS 503 retry backs off without repeated rapid auth checks.

### Main integration E10–E13

Run real Legacy Docker/Chrome acceptance and round-robin/single-/double-elimination tournaments. Verify Player win-rate/form and tie breakers using matches with timestamps and draws. Verify ordinary Organizer result correction changes eligible standings with audit, but **cannot** modify Official or protected tournament matches. Repeat with restarts. Verify v4→v5 migration on disposable backups and compare schema/hash/integrity; never migrate a live volume.

### AWS readiness E14 (review only)

Document target **public Player Internet entry** and **Admin over Tailscale VPN**. Controller/Docker socket/database and internal service networks must remain private. Require separate TLS/Host/Origin/cookie review, backup/restore rehearsal, instance/egress/storage budget, admin emergency access, monitoring, log redaction, recovery objective and rollback plan. Do not provision or deploy anything in Phase 4.2E.

## Release decision

- **PASS:** E01–E14 supported by fresh evidence on a single exact HEAD, no unresolved BLOCKER or MAJOR, security gates clear, evidence reproducible, Codex independently signs off.
- **FAIL:** any mandatory check executes and fails, security boundary is breached, or BLOCKER/MAJOR is unresolved. Never merge/deploy under FAIL.
- **INCOMPLETE:** any required environment, Docker, Chrome, fault injection or evidence is missing. Never quietly convert to PASS.
- Acceptable MINOR observations must be explicitly reviewed and accepted by the project owner. No project merge, production migration, AWS change or deployment without explicit user authorization.

Use [the report template](PHASE_4_2E_QA_REPORT_TEMPLATE.md) and keep the filled report/evidence outside the repository unless sanitized.

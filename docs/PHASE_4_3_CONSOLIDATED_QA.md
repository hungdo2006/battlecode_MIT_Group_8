# NEON ARENA — Phase 4.3 Pre-AWS Consolidated Independent QA

**Scope:** all changes on Draft PR #12, from Phase 4.3A unified login and
self-registration through Phase 4.3B verified-email/Admin MFA and Phase 4.3C
private HTTPS gateway template. This is a **single combined QA run**, NOT
approval to deploy, merge or touch AWS.

**Source of truth:** exact `git rev-parse HEAD` and latest PR files. Re-run
all affected tests if fixes change HEAD. Prior Phase 4.2E QA remains historical
evidence for its own SHA, not new browser/Docker acceptance.

## Safe test setup

- Use clean independent checkouts, disposable SQLite and Docker Compose
  project/volumes only. Record unique project ID and exact ownership of
  resources before cleanup; never run `down -v` on normal development data.
- No AWS, domain/DNS changes, production SMTP account, private Tailscale
  account, live EC2, active database migration or public port-forwarding.
- For verified email QA use an **isolated local fake SMTP server or injected
  SMTP sender** that actually records outbound messages, plus a TLS-capable
  integration fixture. Test STARTTLS certificate failure: no plaintext fallback.
- For public gateway QA use loopback with a trusted local TLS edge and
  simulated Host/Origin, not a public deployment. Verify **actual** Docker
  Compose/Caddy config parsing; static YAML inspection alone is INCOMPLETE.
- Do not print OTP secrets, proxy shared secrets, email tokens, cookies or
  passwords into a report; identify them by hashes or test IDs.

## Mandatory QA gates (all need evidence)

| Gate | Scenario | Acceptance |
| --- | --- | --- |
| P01 | Windows full regression | all `tests controller_tests` PASS; skips explained |
| P02 | Linux full regression | all `tests controller_tests` PASS; skips explained |
| P03 | JS/build/config | `node --check`, version fingerprint, pip check, Compose config parse PASS |
| P04 | Unified login roles | single browser form; backend role from SQLite; no role parameter escalation |
| P05 | Gated local registration | OFF by default (404/UI hidden); ON creates PLAYER only |
| P06 | Input/abuse | valid username/email, Argon2 password, duplicate casefold, 429, 413, injection/Host/Origin |
| P07 | Verified email | registration pending; one-use 24h token; login denied until proof; resend invalidates previous token |
| P08 | SMTP delivery | safe STARTTLS, no fallback, delivery outage and retry, tokens absent from JSON/logs |
| P09 | Admin MFA | offline enroll/rotate, required 6-digit TOTP, invalid/replayed code denied |
| P10 | Session MFA proof | pre-existing password-only Admin session refused when MFA enforced; revocation after rotation |
| P11 | Role/cookie boundary | Path, Secure, SameSite, CSRF, logout, revocation, RBAC/IDOR, WS authorization |
| P12 | Public proxy trust | missing/wrong/multiple edge secret denied; spoofed X-Forwarded/Host/Origin rejected |
| P13 | Real client source | gateway-provided canonical IP only after proof; rate limits cannot be bypassed via audience-specific routes |
| P14 | HTTPS/WSS QA | actual TLS Caddy flow and private edge; no app/controller public port; cookies Secure |
| P15 | Append-only SQLite | fresh and v5→v6→v7→v8→v9 offline migration, checksums/integrity/backup and rollback |
| P16 | Real Player journey | Chrome register → verify → login → Team → bot upload → Official match & replay |
| P17 | Admin journey | Admin TOTP → schedule Official → reviewed result → logout/forced revocation |
| P18 | Fault recovery | startup after Official queued/running claim, idempotency; no fabricated winner |
| P19 | Legacy compatibility | existing invited users, game/tournament/ranks, browser, source attestation and replay unaffected |
| P20 | Handover & go-live boundary | operator runbook, no secrets committed, no AWS side effects, unresolved external-provider requirements explicit |

## Required evidence/commands

```powershell
python -m pip install -r requirements-dev.txt
python -m pip check
python -m pytest tests controller_tests -ra --tb=short
node --check frontend/app.js
node --check frontend/renderers.js
python scripts/version_frontend.py --check
python scripts/check_account_ui.py
git diff --check
```

For Docker, use a dedicated QA project with isolated volumes and real
Sandbox/Chrome. Prepare a local disposable SMTP/TLS test setup. Render the
public overlay configuration with a **dummy** 48+ character proof and a
non-public test hostname:

```powershell
docker compose -f compose.yaml -f compose.public.yaml config
```

Do **NOT** run the public overlay on a live server, publish ports, or provision
external certificates during this test. If the operator cannot exercise local
TLS+Caddy/WebSocket correctly, record P14 INCOMPLETE, not PASS.

## Report requirement

Write `QA_REPORT.md` containing: exact SHA, matrix P01–P20
(PASS/FAIL/INCOMPLETE), reproducible commands, exit codes, test counts,
Chrome test IDs, filtered/sanitized HTTP response/status timeline, Docker
match IDs and replay hashes, migration ledger and source version, cleanup,
all findings by severity, and an explicit **merge recommendation**.

No gate silently passes via inference from pytest or static code inspection.
A FAIL or INCOMPLETE means PR #12 stays Draft. Even 20/20 PASS means AWS go-live
still requires a **separate** approval after organizer-owned domain/SMTP and
network/security-cost review. Codex must not merge, push, deploy or access AWS.

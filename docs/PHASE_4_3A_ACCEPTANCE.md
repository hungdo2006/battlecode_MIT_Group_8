# Phase 4.3A — Independent Acceptance Checklist

**PR candidate only.** Public signup is **gated OFF by default**. This is NOT an
Internet deployment or an approval to migrate an existing AWS/production DB.

## Preconditions

- Clean checkout at **exact PR head SHA**, record base main commit and commit
  statuses. Test on disposable native and Docker data, never operational volumes.
- Offline-migrate a fresh **v5** SQLite fixture to **v6** using the documented CLI
  and verify the five prior ledger checksums, team/schedule rows, Source SHA,
  replay fingerprints and resulting `user_emails` schema. Verify an unmigrated
  v5 DB fails startup (no runtime auto-migration or silent reset).
- Bring up Account-Only local/LAN with `ARENA_SELF_REGISTRATION=1` using Chrome
  and the real sandbox; keep port bound to `127.0.0.1`.

## Acceptance cases

| Gate | Scenario | PASS condition |
| --- | --- | --- |
| A01 | Existing Admin via unified login | no audience selector; account role from server; Admin cookie scoped to `/api/admin` |
| A02 | Existing Player via unified login | Player cookie scoped to `/api/player`, Admin cookie cleared on switch |
| A03 | Invalid password/role injection | uniform 401 / 422; cannot obtain elevated session |
| A04 | Open registration | username/display name/email/strong password → 201 ACTIVE Player only; login after registration |
| A05 | Registration disabled | HTTP 404 and hidden Register choice, no new DB user |
| A06 | Duplicate username/email casefold | 409 without account creation; retries cannot overwrite |
| A07 | Registration abuse | 429 with Retry-After; malformed body, cross-origin/proxy/Host denial; bounded JSON |
| A08 | Session boundaries | CSRF, logout, revocation, WS reconnect, Admin/Player RBAC unchanged; mandatory Admin TOTP when configured, replayed code denied, offline rotation revokes sessions |
| A09 | Database correctness | v5→v6 append-only, idempotent, integrity/FK, existing Admin and Teams survive |
| A10 | Browser integration | actual Chrome signup → shared login Player → logout → shared login Admin; no JS errors |
| A11 | Compatibility | full Windows/Linux pytest, prior invitation activation, Team, Official Match and replay |
| A12 | Security inventory | email unverified; no reset or MFA; public Host/Origin gateway unsupported; no AWS go-live claim |

## Commands

```powershell
python -m pip install -r requirements-dev.txt playwright
python -m pytest tests controller_tests -ra --tb=short
node --check frontend/app.js
node --check frontend/renderers.js
python scripts/version_frontend.py --check
python scripts/check_account_ui.py
python -m pip check
git diff --check
```

Use fresh isolated Docker Chrome cases for A04/A08/A10/A11, including real bot
upload and authorized replay. Record all commands/exit codes, SHA, screenshots,
browser console and container resource cleanup in `QA_REPORT.md`.

**Release decision:** PASS only when every A01–A12 has fresh independent
evidence; FAIL for any privilege escalation, wrong account cookie, data loss
or unverified email used as proof. No merge/deploy without explicit approval.
Even a PASS here does not waive separate Phase 4.3 Internet gateway, TLS,
MFA, email-delivery/verification and anti-automation deployment review.

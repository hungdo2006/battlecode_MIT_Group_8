# Username-only Player registration — optional public mode

This is an explicit product change for a **small supervised class/pilot** on
the existing **Account-Only HTTPS gateway**. It is not a substitute for email
identity verification, enrollment controls, CAPTCHA, or an independent security review.

## Behavior

- One login form remains unchanged. Server derives `ADMIN` vs `PLAYER` from SQLite.
- Player signup requires **username + password** (minimum 15 characters).
  `display_name` defaults to username, `email` is optional and omitted by
  the new frontend when email verification is disabled.
- New accounts are `ACTIVE` and always `PLAYER`. Existing accounts, Teams,
  Admin TOTP credentials and Docker volumes are preserved.
- No email is collected in username-only mode; account ownership **cannot
  be proven through email**. Admins must verify the requesting student by an
  external trusted process before issuing any recovery token.
- Admin issues a one-use recovery token from the Admin-only panel under
  **Official Match → Hỗ trợ khôi phục tài khoản Player**. Issuance requires a
  valid Admin session, CSRF token and (on public gateway) Admin TOTP.
- Admin privately passes the token to the Player. The Player enters it under
  **Quên mật khẩu Player?** and chooses a fresh password. Admin never reads or
  sets the Player's password. A token expires in 30 minutes; issuing a newer
  token invalidates older unspent reset tokens. Successful reset invalidates
  all existing account sessions and outstanding reset tokens. No reset token
  is written to the audit-event details or URL.
- Admin accounts cannot be reset via this Player recovery path.
- Existing email-verification mode remains available when configured with
  an authenticated STARTTLS sender; no code path should silently weaken it.

## Feature gates

Defaults remain **OFF**. On a verified HTTPS public deployment, opt in with:

```dotenv
ARENA_ACCOUNT_AUTH=1
ARENA_ACCOUNT_ONLY=1
ARENA_ADMIN_TOTP_REQUIRED=1
ARENA_PUBLIC_GATEWAY=1
ARENA_PUBLIC_DOMAIN=traitimcodon.duckdns.org
ARENA_SELF_REGISTRATION=1
ARENA_PUBLIC_USERNAME_SIGNUP=1
ARENA_EMAIL_VERIFICATION=0
```

The base `compose.yaml` passes the new flag to Arena; the public overlay also
declares it. Do **not** expose Arena port 8000, Controller port 9000, Docker
socket or SSH publicly. Only Caddy 80/443 should be publicly reachable.

The existing account schema **v9 is unchanged**: usernames and password hashes
remain in `users`, and a `user_emails` record is optional for these users.
A fresh offline migration is **not required** for this feature, but back up all
data/upload/artifact volumes before a deployment and check schema integrity.
Do not run `docker compose down -v`.

## Security and QA before accepting public students

- Account creation has a process-local, per-trusted-client-IP rate limit
  (currently 5 attempts / 60 seconds). This is not globally durable and can
  be bypassed by distributed attackers; deploy an additional edge-level
  protection or private course enrollment control before unrestricted signup.
- Verify recovery identity **out of band**. A username alone is not evidence
  of account ownership. Treat any request to reissue tokens as sensitive.
- Run unit/integration tests, actual Chrome signup/login/password reset,
  MFA/CSRF/source-header spoofing/429 tests, Docker sandbox bot submission and
  full Official Match + replay verification before opening enrollment.
- Tokens are **secrets**. Do not paste them into tickets, logs or public chat.
  They appear once in an Admin response; don't share browser screenshots
  while they are visible.
- If the same username is impersonated/registered by someone else, the app
  cannot determine which claimant is the real student. For a large public
  event, require an organizer-issued enrollment code or verified student
  identity, and reconsider email verification.
- After signoff, the operator may explicitly enable the two signup flags
  on the EC2 `.env`, render/inspect the public Compose configuration, rebuild
  and redeploy. This PR does **not** start, stop or configure AWS.

## Rollback

- Set `ARENA_SELF_REGISTRATION=0` to stop new registrations without
  removing existing Player accounts. Leave `ARENA_PUBLIC_USERNAME_SIGNUP=1`
  while already-issued Admin recovery tokens still need to work, or re-enable
  it after re-review.
- Preserve `arena_data`, `arena_uploads`, `arena_artifacts` volumes.
- Never share an Admin TOTP recovery secret or login password with students.

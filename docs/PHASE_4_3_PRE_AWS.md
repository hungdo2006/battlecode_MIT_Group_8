# Phase 4.3 — Pre-AWS deployment bundle (NOT deployed)

**Stop line:** No AWS credentials, EC2 instance state, VPC, security group,
Route53 records, certificate, Docker production volume or real hostname was
touched by this PR. This is a versioned design and local QA template only.

## Intended handover architecture

- Public Player web UI and Admin web UI share one DNS origin and HTTPS.
- Admin account still uses role-scoped RBAC and **required TOTP MFA**.
- Caddy is the ONLY published web ingress. Public edge forwards to the app
  over a Docker-only network with a high-entropy shared gateway proof. The
  backend rejects missing/multiple/wrong proof, arbitrary Forwarded headers,
  wrong Host or Origin, and uses the edge-supplied canonical public client IP
  only after proof.
- The app retains a separate network to the controller; the Docker socket is
  available only to the trusted controller and never to Caddy or Player.
- Technical operators use an approved private channel (Tailscale, SSM or
  equivalent); do **not** open SSH/SQLite/Controller ports to the Internet.
- Ban tổ chức owns cloud billing, credentials, MFA enrollment, operational
  backup/restore and incident response after handover.

## Configuration template, not launch command

The separate `compose.public.yaml` file removes the app port mapping
(`!reset []`, requires current Docker Compose v2), attaches the app only
to internal `ingress_private` and `runner_private` networks, and adds a
Caddy edge exposing ports 80/443.

`deploy/Caddyfile` strips user-provided identity/proxy headers, replaces them
with a private proof, enforces HTTPS via Caddy-managed TLS and restricts
caching/security response headers. App HTTPS recognition is conditional on
the explicit `ARENA_PUBLIC_GATEWAY=1` option, matched exact hostnames,
enforced Admin TOTP, and secret (48+ characters). Without the correct proof,
Account-Only endpoints deny public/proxy requests.

To **review static config only** (no resources created):

```powershell
# Configure placeholder variables in a disposable QA shell first.
docker compose -f compose.yaml -f compose.public.yaml config
```

Do not use `docker compose up` until independent security/browser/Docker QA and
an explicit deployment authorization.

## Mandatory blockers before any public go-live

1. Obtain and verify an organization-owned domain and TLS reachability.
2. Confirm SMTP credentials/delivery and verified-email registration workflow.
   v8 issues one-time 24-hour hashed verification tokens and keeps Players
   INVITED until their email is verified. A registration email link uses URL
   fragments to avoid leaking the token via the initial HTTP request. The
   public overlay defaults self-registration OFF; enabling it REQUIRES
   ARENA_EMAIL_VERIFICATION=1, a working authenticated STARTTLS sender, real
   abuse/security review and Chrome/Docker acceptance. When the registration
   window closes, keep ARENA_EMAIL_VERIFICATION=1 and the SMTP sender configured
   so pending Players can verify and existing verified Players can reset their
   passwords; ARENA_SELF_REGISTRATION=0 alone blocks new signup. Never claim
   production signup ready from the HTTP tests alone.
3. Enable and enroll Admin TOTP offline on organization-owned devices. Test
   phishing resistance procedures, shared-password avoidance and recovery.
4. Independent Chrome+Docker+TLS/WebSocket adversarial QA, including source
   spoofing, 429 rate limits under many real IPs, CSRF, role/Team IDOR,
   bot sandbox side effects, queued/running crash recovery and replay privacy.
5. Prove one exact Compose render contains **no public Arena port**, no
   Controller/Docker socket Internet exposure, no backup/credentials in images.
6. Migration rehearsal with supported v5→v6→v7→v8→v9 on a **disposable snapshot**
   of the existing account DB; validate integrity and rollback.
7. Production backup (data, uploads, artifacts, replay), restore runbook,
   credential rotation, disk budget/alarms, least-privilege access,
   log retention/redaction and incident escalation must be owned by organizers.
8. Approved AWS and billing plan. No public EC2 security-group rules, EIPs,
   Route53, Tailscale organization accounts or email-provider setup in code QA.

## Handover criterion

A fresh technical operator must reproduce start/stop, self-contained
configuration, Admin login with TOTP, Player signup once enabled, bot
submission, Official match, replay, backup, restore, session revocation and
rollback **solely from the handover docs**, with temporary credentials owned
by the organizers. Failure means NOT READY, even if unit CI passes.

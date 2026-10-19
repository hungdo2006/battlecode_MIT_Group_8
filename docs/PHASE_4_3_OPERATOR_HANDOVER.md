# Organizer handover runbook — predeployment draft

NEON ARENA is a self-hosted application. The organizing committee must be
able to operate it without the development team's cloud, Tailscale, GitHub
or SMTP credentials. These instructions are a checklist; no AWS provisioning
has been executed.

## Roles and ownership

- **Player:** public web account, email verification, Team and bot ownership.
- **Organizer Admin:** app-only role via credential + TOTP, match scheduling
  and audited controls; no access to EC2, Docker socket or SQLite required.
- **Technical Operator:** organizer-owned SSH via approved private access
  (Tailscale/SSM/organizational VPN), offline DB migration, backups, rollback,
  monitoring and incident response.
- **Developer:** no standing operational access after handover; use
  time-limited, explicitly approved assistance.

## Pre-install and change checklist

1. Obtain domain, DNS authority, mail sender provider, TLS reachability,
   low-cost AWS budget, RTO/RPO, monitoring and on-call contacts.
2. Back up **data + uploads + artifacts** and replay storage before any
   migration or deployment. Test restoring into an isolated machine.
3. Provision a fresh SQLite v9 database with a writer lock, or rehearse
   offline migrations on a data snapshot; never auto-migrate a running DB.
4. Independently enroll each Admin's MFA with a private terminal; store
   recovery procedure offline. Require TOTP in gateway configuration.
5. Configure separate high-entropy Runner token and Gateway proxy secret.
   Secrets must not be committed, echoed or included in Docker images/logs.
6. Check the exact Compose overlay with the operator's approved Docker
   Compose v2 version. Backend and controller must have no published ports;
   only Caddy 80/443 may be Internet-facing.
7. Configure SMTP sender and verify STARTTLS, delivery, token invalidation
   and failure recovery before enabling registration.
8. Run and archive complete P01–P20 QA evidence on exactly the deployed
   image/source SHA. Test a full Player/Team/Official match on a staging copy.
9. Agree rollback triggers, artifact retention and emergency account revocation;
   rotate all initial developer-known tokens on transfer.
10. Obtain final user/organizer authorization separately for AWS deployment.

## Operational drill

The technical operator should demonstrate routine deploy/restart, safe
shutdown/drain, database integrity, daily encrypted backup, checksum
verification, independent restore, controlled Admin MFA rotation, session
invalidation, successful Official dispatch/replay and recovery without
invented winners. Test unverified email signup and SMTP failure handling.

## Hard stop

No AWS deployment, port rule modification, domain provisioning or migration of
active data is authorized by this document. Domain/SMTP credentials and the
organizer-owned infrastructure are not yet configured in the repository.

# Offline → Online results (laptop pilot, v1)

NEON ARENA can run a practice offline school competition using **a laptop with Docker Engine/Desktop (Linux containers)**. The dedicated school server is an optional later hardware upgrade. The existing LAN exam configuration is `compose.exam.yaml` with `docs/EXAM_MODE.md`; that network must be prepared and tested separately. **Do not apply exam overlay to AWS.**

## Workflow

1. Before the event, generate a secret of at least 32 random characters. Set the SAME value for `ARENA_OFFLINE_RESULTS_KEY` in the private `.env` on the **offline host** and **online host**. Never commit or print the key. The online server does not need `ARENA_OFFLINE_SITE_ID`.
2. Set a unique `ARENA_OFFLINE_SITE_ID` on the laptop, e.g. `school-lab-2026`. Configure the offline Exam LAN HTTPS, local DNS, Caddy CA trust, admin account + MFA and Docker Sandbox while internet is available. Test it with two teams and actual bots.
3. Hold the offline competition. Only a completed Team Tournament with all Official fixtures completed is eligible.
4. On offline Admin > **Giải đấu**, click **Xuất kết quả offline**. The browser saves `neon-results-<id>.json` with the finished, public-only results and a SHA256 HMAC signature.
5. Transfer that JSON file to the online Admin securely. On online Admin > **Giải đấu** > **Nhập kết quả giải offline**, select it and click **Kiểm tra & xem trước**. Verify the venue, tournament name, teams, match count and game.
6. Confirm publication explicitly. The verified result appears at `/results` in a **separate offline category**. The file may be re-imported without duplication. Conflicting updates to a published event are refused.

Signing and verification use a **shared secret** known to both servers. This authenticates the export only as strongly as its secret management. If the secret is missing, the feature fails closed. Do not send the secret in the export file, a bug report, or screenshots. Rotate keys through a planned process *between* events; changing the key prevents validating files signed with the old one.

## Deliberate safety boundaries

- **No SQLite migration, no overwrite of existing AWS users, teams, tournaments, standings or Official match results.** Imported results live in `arena_data/offline_publications.json`, isolated from online tournament authority.
- The signed package contains venue ID, tournament name and game, team-name snapshots, standings, match winners and bracket. No password, e-mail, Team UUID, bot source, compiled artifact, private replay path, player token, session ID or admin secrets are exported.
- This v1 publishes results and a text match history. **Replay transfer is not yet implemented.** Keep the offline server's own archive/backups for replay until a future separately verified replay-export feature.
- Only Admin can export, preview or import. Preview does **not** publish; publish requires explicit confirmation, valid login/CSRF and a matching HMAC. Public viewers can only GET allowlisted summary data.
- A pending or interrupted tournament cannot be exported. Imported events cannot mutate existing offline snapshots: changed content for the same source/tournament ID is rejected.
- Protect `offline_publications.json` with normal Docker volume backups, separate from your competition database backups. Avoid manual editing.

## Laptop pilot first

Without a server from school, start by running tests/CI and one LAN dry run with two temporary teams on the laptop. Measure actual CPU/RAM and keep the concurrency cap at **2**. Later, move only the offline deployment to a more powerful school PC after hardware acceptance; no changes to the export format are required.

Full dry run: create a local offline tournament, complete Official matches, export JSON, use a **staging** online installation with the same signing key, preview + import, and verify it appears at `/results` while unrelated online tournaments, source and replay remain unchanged. Do not test an unverified import for the first time on production AWS.

Future milestones: signed replay bundles and integrity checks; richer offline results page; opt-in remote runner with isolated credentials, resource-aware scheduling and throughput benchmarks. The current Controller only trusts its Docker private network and must never be exposed directly.

# Offline → Online results (laptop pilot, v1)

NEON ARENA can run a practice offline school competition using **a laptop with Docker Engine/Desktop (Linux containers)**. The dedicated school server is an optional later hardware upgrade. The existing LAN exam configuration is `compose.exam.yaml` with `docs/EXAM_MODE.md`; that network must be prepared and tested separately. **Do not apply exam overlay to AWS.**

## Workflow

1. The offline LAN helper in the README generates `ARENA_OFFLINE_RESULTS_KEY` (32+ random characters) and `ARENA_OFFLINE_SITE_ID` in its private `.env`. For import, the online deployment needs the SAME signing key, installed through a separately reviewed and tested maintenance procedure. **B1.5 EC2 pilot does not forward this key by default.** Do not edit pinned B1.5 Compose models or runtime env by hand. Never commit or print the key. The online server does not need `ARENA_OFFLINE_SITE_ID`.
2. The helper generates a unique site ID (or preserves an existing one). Configure the offline Exam LAN HTTPS, local DNS, Caddy CA trust, admin account with username/password and Docker Sandbox while internet is available. Test it with two teams and actual bots.
3. Hold the offline competition. Only a completed Team Tournament with all Official fixtures completed is eligible.
4. On offline Admin > **Giải đấu**, click **Xuất kết quả offline**. The browser saves `neon-results-<id>.json` with the finished, public-only results and a SHA256 HMAC signature.
5. Transfer that JSON file to the online Admin securely. On online Admin > **Giải đấu** > **Nhập kết quả giải offline**, select it and click **Kiểm tra & xem trước**. Verify the venue, tournament name, teams, match count and game.
6. Confirm publication explicitly. The verified result appears at `/results` in a **separate offline category**. The file may be re-imported without duplication. Conflicting updates to a published event are refused.

Signing and verification use a **shared secret** known to both servers. This authenticates the export only as strongly as its secret management. If the secret is missing, the feature fails closed. Do not send the secret in the export file, a bug report, or screenshots. Rotate keys through a planned process *between* events; changing the key prevents validating files signed with the old one.

## Deliberate safety boundaries

- **No SQLite migration, no overwrite of existing AWS users, teams, tournaments, standings or Official match results.** Imported results live in `arena_data/offline_publications.json`, isolated from online tournament authority.
- The signed package contains venue ID, tournament name and game, team-name snapshots, standings, match winners and bracket. No password, e-mail, Team UUID, bot source, compiled artifact, private replay path, player token, session ID or admin secrets are exported.
- This v1 publishes results and a text match history. **Replay transfer is not yet implemented.** Keep the offline server's own archive/backups for replay until a future separately verified replay-export feature.
- The public page also shows bracket decisions (including an Admin-resolved tie), byes and unplayed conditional resets. A reset that was not needed is exported as `SKIPPED` with no participants or match winner; it is not an extra played match. Unresolved bracket slots cannot be exported.
- Only Admin can export, preview or import. Preview does **not** publish; publish requires explicit confirmation, valid login/CSRF and a matching HMAC. Public viewers can only GET allowlisted summary data.
- A pending or interrupted tournament cannot be exported. Imported events cannot mutate existing offline snapshots: changed content for the same source/tournament ID is rejected.
- Protect `offline_publications.json` with normal Docker volume backups, separate from your competition database backups. Avoid manual editing.

## Laptop pilot first

Without a server from school, start by running tests/CI and one LAN dry run with two temporary teams on the laptop. Measure actual CPU/RAM and keep the concurrency cap at **2**. Later, move only the offline deployment to a more powerful school PC after hardware acceptance; no changes to the export format are required.

Full dry run: create a local offline tournament, complete Official matches, export JSON, use a **staging** online installation with the same signing key, preview + import, and verify it appears at `/results` while unrelated online tournaments, source and replay remain unchanged. Do not test an unverified import for the first time on production AWS.

Future milestones: signed replay bundles and integrity checks; richer offline results page; opt-in remote runner with isolated credentials, resource-aware scheduling and throughput benchmarks. The current Controller only trusts its Docker private network and must never be exposed directly.

## Release verification (before merging or touching AWS)

The regression suite exercises HMAC signing, invalid records, access controls, CSRF,
preview-only mode, tamper rejection, duplicate imports, conflict rejection and the
public results API. Run it against the PR head on Linux/Windows, and confirm the
asset version checker passes:

```bash
python -m pytest tests/test_offline_results.py tests/test_offline_results_http.py -ra
python -m pytest tests controller_tests -ra
python scripts/version_frontend.py --check
node --check frontend/app.js
node scripts/check_public_results_rendering.cjs
```

With Playwright and local Chrome, `python scripts/check_offline_results_ui.py`
checks file selection, preview without publication, tamper rejection, explicit
publication, duplicate import and anonymous desktop/mobile results on a
temporary localhost server. It uses a **synthetic signed event**, not Docker or
a completed offline competition. It does not replace the two-host release gates.

**These tests do not establish that a real LAN tournament or a two-host Docker
transfer works.** Before promotion, the operator must record the PR commit SHA
and independently rehearse the following steps with fake accounts/data:

1. In a *dedicated offline staging* installation (not the live AWS data volume),
   prepare two test Teams and bot artifacts. Complete a tournament with real
   Sandbox execution, verify Official results and replay, then export its JSON.
2. Move that JSON to a **separate online staging installation** configured with
   the same signing secret. Do not put the shared secret in the package or logs.
3. Verify the preview matches the venue, tournament and expected team/match
   counts. Confirm that merely previewing makes nothing public.
4. Test rejection of an altered byte, another secret, and missing CSRF; confirm
   no publication occurs. Publish only the original signed package.
5. Open public `/results` without a session. Verify the correct offline
   scoreboard and match winners, no private source, identifiers or replay.
   Re-import the same package (no duplicate); try an independently re-signed
   conflicting package for the same venue/tournament (must be rejected).
6. Restart the online Arena without deleting Docker volumes. Confirm the offline
   publication survives and online users, tournaments, Official history, replay
   and scores have not changed. Back up and restore the staging data volume.
7. Record PASS/FAIL/SKIP, source SHA, image IDs, Docker versions, host/OS,
   screenshots with credentials redacted and observed CPU/RAM. Any failure
   blocks deployment; a passing unit test alone is not a release sign-off.

Do not run the offline Exam overlay and Internet/Public overlay on the same
host, expose the Controller Docker socket, or use production participants to
validate the feature.

## Remote runner boundary

This milestone transfers *results files*, not live execution jobs. The existing
two-match cap and Controller on-host Docker boundary are intentional. A dedicated PC as a Remote Worker is supported by B1.5, but its deployment is
independent of offline result export. Increasing concurrency or adding Workers requires a separate threat model,
mutually authenticated transport, one-way work queue, artifact attestation,
resource limits and crash recovery. It must be implemented and benchmarked in
a separate change; merely opening port 9000 or forwarding the Docker socket
is unsafe.

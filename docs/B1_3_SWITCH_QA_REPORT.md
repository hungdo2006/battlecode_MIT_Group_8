# B1.3 runner switch QA — 2026-10-24

Issue: [#31](https://github.com/hungdo2006/battlecode_MIT_Group_8/issues/31).
Branch: `feat/b1-3-reversible-runner-switch-20261024`, based on merged main
`043c6b1b8aa02cbd6ed87797319b660ff325b2a6`. PR #30 changes are not included.

**Local preparation and rehearsal PASS. Live EC2/Internet cutover BLOCKED.**
No AWS access, SSH, deployment, new server, port opening, production data change
or merge was performed. Existing non-QA volumes were not mounted or modified.

## Implemented

- Operator CLI: capture full resolved Compose, redacted status/preflight,
  persistent drain/resume, local/remote switch and failed-transition rollback.
- Immutable image IDs, same Engine/project/mount checks, original file hashes,
  exclusive per-site operation lock and fresh process acknowledgement.
- New uploads/matches/dispatch stop during drain. Busy work and pending cleanup
  refuse service stops. No automatic runtime fallback or fake Official winner.
- Remote config has only Arena/Caddy. It removes local Controller dependencies,
  URL/token and socket access, retains account/signup/password-only settings,
  Caddy bindings and original data/uploads/Caddy volume identities.
- Stable Controller artifact-store attestation prevents treating a cloud-only
  artifact as available on PC just because the image ID matches.
- Complete cold backup of five volumes, referenced image inventory/archives,
  exact private configuration, Caddy state/image and restore drill on new volumes.
  Drill verifies archive/file hashes, SQLite integrity/foreign keys and schema 20.
- Operator procedure and future Admin control-plane boundary documented in
  [RUNNER_SWITCH_B13.md](RUNNER_SWITCH_B13.md). No Admin button/public switch API.

## Verification

All Docker execution used one Windows laptop, Docker Desktop Linux engine
29.8.2 / Compose 5.6.0. HTTPS was real TLS on a private Docker network with an
ephemeral internal QA CA. **This is not Internet or two-physical-machine proof.**

| Check | Result / scope |
| --- | --- |
| Full Python + Controller regression | PASS: 702 tests at full-suite collection; later final focused suite 53 PASS, including five additional tests (707 tests in final source) |
| Actual Compose order | PASS: repository base + synthetic private override + public overlay; exact `neon-arena` resource names, two remote services, preserved flags/ports and literal-dollar round trip; no site containers started |
| B1.3 Docker switch rehearsal | PASS: 11 acceptance groups, unique cloud/worker projects |
| Cold backup + restore | PASS: all five volumes, historical image references, private files and Caddy; new restore volumes; final SQLite integrity/foreign-key/schema 20 probe PASS |
| Missing PC Worker | PASS: remote readiness failure triggered actual Docker rollback to ready local mode before target admission |
| Busy switch | PASS: refused while two Official matches ran; no stop; explicit same-mode resume completed queue |
| Local → remote → local | PASS: same persistent mounts; local Controller stopped in remote mode; Caddy container retained across cutover |
| Artifact identity | PASS: cloud artifact rejected on PC with the same image; original local artifact runs a new Official after rollback |
| Data persistence | PASS: historical Official outcome/replay unchanged; new remote outcomes/replays and tournament standings survived return to local |
| Capacity | PASS: two concurrent Official matches, third queued, cap remains 2 |
| Final actuator safety | PASS: additional actual Docker round trip with exclusive operation lock and status timestamp after container start |
| Extended B1 Docker regression | PASS: 21 groups, Python/C++/Java compile/runtime, invalid C++, bot crash/timeout, authentication, disconnect/reconnect, Controller/cloud restart, old/stale responses, new Official after recovery |
| Browser | PASS: Playwright Python + Chrome, 0 JavaScript errors; MCP was not used; browser CA exception limited to QA context |
| Frontend routing/assets, syntax, whitespace | PASS |
| GitHub Actions | See PR checks for final commit: Ubuntu/Windows regression and new read-only Compose config job |

Repeatable commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests controller_tests -ra --tb=short
.\.venv\Scripts\python.exe scripts/check_b13_compose_config.py
.\.venv\Scripts\python.exe scripts/check_b13_switch_docker.py --build
.\.venv\Scripts\python.exe scripts/check_b1_real_world_qa.py --evidence .qa-evidence/b13-full-b1
```

Private local evidence: `.qa-evidence/b13-6a9cf9ca97.json` (11 groups),
`.qa-evidence/b13-full-b1/extended-results.json` (21 groups), regression JUnit,
protected switch/backup/drill bundles under `.runner-switch/`. Evidence, dummy
accounts, certificates, env files and large image archives are excluded from PR.
The full B1 harness removed only its label-verified disposable QA resources;
the new switch harness stopped its own projects and retained volumes/backups.
Earlier failed rehearsal attempts also retain their QA volumes for inspection.

QA image identities (local build, not deployment images):

| Image | ID |
| --- | --- |
| Arena | `sha256:7d2368945c0b93de592bb687a062de0e6c6008d4e3b6da8fe723d6da93214511` |
| Controller | `sha256:75484762a3953186b1b8cffd67498a0aa38fdd1299121e8da0f4011dcd2f55c8` |
| Bot | `sha256:41ee0f26487b0431b8f017d41c4dc6474998cdcac3828a8a24428d251209424d` |
| Agent | `sha256:10a170eb193fd25f187d0e8f4be7ec0e73294d1beb06198c18766ab79e8f2ecf` |

## Findings corrected during preparation

1. Compose JSON config escapes literal dollars. Re-encoding without decoding
   changed `$`-containing credentials. Fixed semantic decoding/encoding and
   verified both resolved model and actual QA container value.
2. Compose drops unused network/volume declarations. Remote model now contains
   only used resources; original artifact volume stays in local rollback plan
   and Engine. No deletion occurs.
3. Windows newline conversion broke a byte-derived plan comparison. Replaced
   it with a canonical, platform-independent plan fingerprint.
4. Image identity alone missed artifact storage changes. Stable store identity
   now fails closed for old/other-host artifacts without rewriting history.
5. A freshly restarted container could otherwise read a recent status from its
   predecessor. Readiness now requires an acknowledgement after container start.
6. QA assertions were corrected to observe whichever two of three requests are
   actually dispatched, and to compare Caddy identity after the intentional cold
   backup restart. These were harness errors, not live-site incidents.
7. Resume is an explicit transaction boundary: lost resume acknowledgement or
   failed commit audit must not roll back possibly admitted Official jobs. Both
   negative paths are covered by regression tests.

No unresolved failure remains in the exercised local acceptance paths. FastAPI
TestClient emits an existing httpx deprecation warning; it did not fail tests.
One elevated pytest invocation could not create its default temporary fixtures;
rerunning with a fresh QA workspace temp directory completed all 53 focused tests.

## BLOCKED / remaining operator work

The owner supplied likely file order, project/volumes and previous auth flags,
but explicitly has not re-verified them on running EC2. Do not infer current
state. Public origin/certificate is unknown; no registered domain is confirmed.
**Do not authorize cutover until system-trusted public HTTPS works from Windows.**

1. Review/merge only by maintainer; record actual source, redacted effective
   configuration, mounts, image IDs, schema, jobs and auth/signup flags privately.
2. For an old image without drain protocol, arrange explicit downtime and a
   separately approved cold backup/upgrade to switch-aware local mode. Toolkit
   refuses to auto-switch such an image. Old bot records need source re-upload.
3. Take a fresh complete EC2 cold backup, recover any missing historical image,
   encrypt/copy off-host and run file/SQLite restore drill plus isolated restored
   application/account/replay/match acceptance. Local QA is not EC2 backup proof.
4. Provision independent secrets privately, prepare no-sleep Windows Worker,
   verify actual Internet TLS, then operator executes the reviewed commands.
5. Run Internet acceptance for languages, two matches/queue, replay/standings and
   supervised network/PC sleep recovery. Real WAN latency, laptop power events,
   public proxy behavior and live settings remain untested.

Same-image/schema mode rollback retains current data and reattaches original
local artifacts. New PC bots may need re-upload locally; frozen requests using
the other store may block. Returning to a pre-upgrade image after a later schema
migration requires a verified compatible snapshot, never a blind downgrade.

# Complete Retro Pixel workspace review

Implemented on `feature/retro-pixel-ui-redesign`. Ready for the owner's visual
review. No merge, AWS deployment, operational Runner change or live-data mutation.

[Desktop/mobile screenshot gallery](screenshots/retro-workspace/README.md)

## Architecture and scope

The application remains a vanilla HTML/CSS/JavaScript frontend. The audit found
an approved landing in `landing.css`, a separate workspace foundation in
`styles.css`, independent inline public-results styling, and canvas colors in
`renderers.js`. Existing task-based journeys already derive readiness, membership,
permissions and schedules from server responses. Those contracts remain intact.

- `frontend/tokens.css` now owns local font faces and the shared palette, spacing,
  radius and motion tokens. Existing semantic and legacy color aliases resolve
  to the retro palette so older UI contracts continue working.
- `frontend/styles.css` applies the foundation to navigation, overview, teams,
  submissions, tournaments, Seasons, schedules, practice, standings, replay,
  profile, account management, system status and supporting documents.
- `frontend/results.css` replaces the public scoreboard's separate inline theme.
  `results.html`, `protocol.html` and `lan.html` consume the shared font foundation.
- `frontend/app.js` changes only practice-row presentation: existing status text
  receives the shared status badge and a status attribute. Requests, state
  transitions, validation, permissions, routing and polling are unchanged.
- `frontend/renderers.js` changes color literals and the color legend only.
  Saved frame interpretation, board geometry, game selection, timing and bot
  execution are unchanged. The favicon uses the existing pixel N motif.
- `scripts/version_frontend.py` fingerprints the additional CSS assets.
  `scripts/arena_ui_release.py` verifies 17 frontend files, including shared
  tokens, supporting pages, renderers, both active fonts and their licenses.

No backend, schema, auth/session/CSRF code, API endpoint, runner configuration,
Compose file, production setting or secret was changed.

## Design and UX decisions

Handjet 550, with the approved `ELSH 2` / `ELGR 1` axes, carries major headings,
branding, readiness headings and prominent counts. Inter handles functional
labels, card titles, forms, tables and paragraphs; code and technical identifiers
use the monospace stack. Both active fonts remain self-hosted with bundled OFL
licenses. The approved Handjet binary is unchanged.

The palette is charcoal `#121212`, surface `#1B1B1B`, mint `#48D5AE` and cream
`#F2EFE6`. Panels have 2–4 px corners, flat surfaces, quiet borders and no colored
glow. Green, amber and coral remain semantic feedback colors with text or symbols.

The cream overview makes the actual next action prominent for each role. Existing
team readiness steps, bot eligibility explanations, Captain-only controls and
contextual links remain based on real server state. Guidance and secondary text
are larger; functional controls retain Inter and Vietnamese accents have more
vertical space. Tournament summaries use the available width rather than
compressing titles into a narrow column. Full-width disclosure headers make
forms easier to open, with destructive confirmation and role restrictions kept.

Practice rows distinguish waiting, running, completed, interrupted and cancelled
states using the shared badge. The existing practice filters, eligibility,
opponent search and replay actions remain available. Admin tables keep their
compact density and horizontal scroll regions; public standings now provide a
keyboard-focusable scroll region. Major forms and expanded tournament details
were measured as well as initial views.

Navigation, dialogs, notifications and page entry use short transform/opacity or
color transitions. There are no new polling-triggered row animations. Reduced
motion disables CSS animation and transitions; replay playback retains its
existing explicit controls.

## Executed verification

Chrome on Windows, with isolated temporary accounts/data; no production data:

| Check | Actual result |
| --- | --- |
| `python -m pytest tests controller_tests -q -o addopts= --tb=short` | **767 passed**, 211.85 s; one existing Starlette/httpx deprecation warning |
| `scripts/check_account_ui.py` | Passed registration/login, restore, logout/retry, mobile navigation/focus, revocation, password confirmation, multi-tab logout and legacy 410 |
| `scripts/check_workspace_layout.py` | **132** role/view/width cases; real team creation/activation, invitation acceptance, upload/Active Bot, account pagination/search, keyboard tabs, tournament/round rules publication, Season creation, future scheduling, error recovery and logout |
| `scripts/review_workspace_redesign.py --capture` | **210** populated and expanded role/view/width cases; no document overflow, duplicate IDs or page errors; mobile drawer, actual network loss/recovery and reduced-motion CSS verified |
| `scripts/review_workspace_redesign.py --capture --url http://127.0.0.1:8880` | **6** replay widths; real Docker Sandbox practice with **10 saved frames**; play, pause, keyboard seek, reset, speed and downloaded replay JSON verified |
| `scripts/check_multiplayer_ui.py --lan-ip 127.0.0.1 --output-dir .qa-evidence/application-redesign/legacy` | Three independent legacy sessions, real Robot Battle and OTT matches (**10 / 28 frames**), invitation/role enforcement, reconnect, independent pause, historical replay and mobile navigation passed |
| `scripts/check_offline_results_ui.py` | Signed synthetic package preview, file-change invalidation, tamper rejection, explicit publication, duplicate import and anonymous results/bracket/history passed at desktop/mobile |
| `scripts/check_retro_landing_ui.py --output-dir .qa-evidence/application-redesign/landing` | Five landing widths, fonts/art, navigation/auth proxies, no-JS, disabled registration, reconnect and reduced motion passed |
| Node routing and public-results runtime checks | Both passed, including CSRF routing, stale calendars and adjudicated/BYE/draw result rendering |
| JS syntax, asset fingerprints, `git diff --check` | Passed |
| Local frontend image verification | Exactly one frontend COPY layer; runtime config unchanged; all **17** guarded files match checkout |
| Extended release-guard regressions | **16 passed**, including refusal of missing shared tokens, public-result assets, renderers, active fonts or licenses |

Both layout matrices cover **320, 360, 390, 768, 1024 and 1440 px**. The older
browser helpers were updated to use the existing advanced-navigation disclosure,
the dedicated replay route and tournament-scoped rules; the application was not
changed to restore obsolete test assumptions.

Landing comparison against `.qa-evidence/typography-a-final`: image dimensions
match at all five widths and the landing content pixels are identical. At four
widths only the rightmost 15 px scrollbar gutter changes to the shared charcoal
background; the 320 px capture is completely identical.

Full local evidence is under `.qa-evidence/application-redesign/`, including
`layout-report.json`, `replay-report.json`, `pytest.xml`, `image-report.json` and
`landing/approved-comparison.json`. Selected screenshots are committed in the
gallery; their accounts, teams and competitions are disposable QA fixtures.

## Reproduction and limits

Use the project's `.venv` Python. `scripts/review_workspace_redesign.py --capture`
owns and removes a native test runtime. Native mode does not pretend to execute
asynchronous sandbox practice. For actual execution, `--serve --docker --port
8880` creates a random `neon-arena-qa-*` Compose project, private named volumes and
QA image tags. Only its frontend is mounted read-only from the checkout. Run the
replay capture against that dedicated instance. Ctrl+C or the helper's
`.qa-evidence/application-redesign/stop-review` marker triggers its scoped cleanup.
Operational Worker containers and their volumes are never used by this helper.

No UI failures remain from the executed checks. Firefox, Safari, actual phone
hardware, public HTTPS, AWS staging and a live Local/Remote Runner transition
were not exercised. Offline browser evidence uses a deliberately signed synthetic
event, not an independently run offline competition. Browser coverage exercises
import/publication; export contract coverage comes from the regression suite.
There is no claim of a complete WCAG audit. The local QA image was built and
verified without deploying it.

Implementation commits: `23240e5` (foundation), `a1fd466` (Player/Admin hierarchy),
`aafb541` (supporting pages/replay). The following QA commit contains this report,
the browser-helper updates and review screenshots.

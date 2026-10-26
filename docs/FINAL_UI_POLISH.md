# Final UI polish and release readiness

Final refinements to the approved redesign at `6bda6ff`, on
`feature/retro-pixel-ui-redesign`. Ready for final owner approval; no merge,
AWS deployment or production-data change.

[Updated desktop/mobile screenshots](screenshots/final-polish/README.md)

## Changes

1. **Game context:** account-only workspace screens show “Trò chơi” and the
   selected game name. The verbose default-configuration badge is hidden and
   cleared. Legacy competition phase labels remain available in legacy mode;
   game selection, locking and tournament-specific rules are unchanged.
2. **Admin tables:** the accounts table shows “Vuốt ngang để xem đầy đủ” only
   while its content exceeds the visible width. A ResizeObserver keeps the hint
   accurate across resizing and tab visibility changes. The focusable scroll
   region references the hint via `aria-describedby`; screen readers also receive
   keyboard instructions. All five columns, row actions, search and pagination
   remain intact. Focus can still scroll administrative actions into view.
3. **Replay HUD:** team/player name and language/bot name have separate text
   elements. At widths up to 600 px, Player A and B occupy full-width stacked
   rows with explicit labels, mint/cream side marks and aligned HP information.
   Names wrap without truncation. Desktop keeps the opposing layout. Existing
   snapshot/fallback identity precedence and combined result/log labels are
   preserved; bot labels are cleared during replay reset and logout.

The implementation changes `frontend/app.js`, `index.html`, `styles.css` and
`ui.js`; `lan.html` and `protocol.html` only receive updated shared-asset
fingerprints. Browser helpers assert the revised HUD and table behavior.
No renderer, engine, playback, auth/CSRF, backend, data format, font, token,
illustration, navigation or motion-system implementation was changed.

## Executed checks

| Check | Actual result |
| --- | --- |
| Full `pytest tests controller_tests` | **773 passed** in 196.86 s; one existing Starlette/httpx deprecation warning |
| Populated workspace browser review | **210** role/view/width checks passed, including expanded forms, Admin tabs, conditional table hint, keyboard scrolling/action focus and no document overflow |
| Existing workspace journey suite | **132** role/view/width checks passed; team creation/activation, invitation, upload/Active Bot, accounts/search/pagination, tournament round-rule publication, Season creation, scheduling and error recovery |
| Real Docker Sandbox replay | **10 saved frames**, **6** widths passed; distinct team/bot/HP labels, stacked mobile rows, no clipped HUD text, play/pause, keyboard seek, speed, reset, JSON download and logout cleanup |
| Account browser suite | Passed registration/login, session restore, logout/retry, mobile navigation/focus, revocation, password confirmation and multi-tab logout |
| Legacy multiplayer browser suite | Three sessions; real Robot Battle/OTT matches with **10/28 frames**, permissions, invitations, reconnect, independent pause, historical replay and mobile navigation passed |
| Landing browser suite | Five widths, fonts/art, auth entry points, no-JS, registration states, reconnect and reduced motion passed |
| Landing image comparison | **Zero changed pixels** at 320, 360, 390, 768 and 1440 px against the approved pre-polish captures |
| Node routing/public-results checks | Both passed |
| JavaScript syntax, fingerprints, whitespace | Passed |
| Local frontend image compatibility | One frontend COPY layer over the approved QA image; unchanged runtime config; all **17** guarded assets/font licenses match checkout |

Workspace and replay measurements cover **320, 360, 390, 768, 1024 and 1440 px**
in Chrome on Windows. The browser checks also verify reduced-motion CSS and
actual network loss/recovery. All accounts, teams, tournaments and matches in
the screenshots are disposable QA data. The Docker check uses its own random
Compose project and private volumes, never operational Worker data.

Local evidence is under `.qa-evidence/final-polish/`: pytest XML, layout/replay
reports, landing captures and comparison JSON, legacy screenshots and the image
compatibility report. The six selected review screenshots are committed.

## Remaining limits and approval boundary

No failing checks or release blockers remain from this pass. Firefox, Safari,
physical phones and public HTTPS/AWS staging were not tested. This pass does not
claim a full assistive-technology/WCAG audit. The existing dependency deprecation
warning is unrelated to these refinements.

Review is limited to the feature branch. Merge and production rollout still
require the owner's final approval.

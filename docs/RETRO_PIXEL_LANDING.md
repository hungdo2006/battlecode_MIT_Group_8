# Retro Pixel landing — Milestones 1–3

Branch: `feature/retro-pixel-ui-redesign`. Baseline: `11a0711` (26/10/2026).
Scope: public landing and its account-entry dialog; stop here for visual review.

## Design

The supplied reference guides the dark canvas, warm cream cards, mint accents,
rectangular controls and vintage-computer illustration. The original SVG is a
strategy room with a CRT bot grid, keyboard, lamp, plant and books. It is explicitly
labelled as an illustration and does not claim to show a live match or player counts.

The hero reads “Viết code. Đấu trí. Để bot lo.” Its login/register controls lead to
the existing forms. Three cream cards cover writing bots, competing with a Team
and learning from replay; a three-step guide and closing CTA complete the page.
Mobile has a keyboard-accessible disclosure menu, rather than a modal overlay.

## Foundation and compatibility decisions

- `landing.css` owns the `--retro-*` palette, type, spacing, borders, radii,
  shadows and motion. Application semantic aliases opt in only inside
  `.account-landing` and the account dialog/toast while the landing is active.
  Authenticated Player/Admin views retain their current styling.
- Old landing rules were removed from `styles.css` to avoid competing cascade
  rules. Workspace visibility, layout, forms, renderer styles and navigation
  remain in that stylesheet.
- Colors: background `#121212`, surface `#1B1B1B`, mint `#48D5AE`, warm white/cream
  `#F2EFE6`, muted `#AAA9A2`, border `#363833`. Semantic success `#79DBAC`, warning
  `#EFCA7C`, error `#FF9A91`. Buttons use dark text on mint. No gradients or glow
  in the landing design.
- Display: self-hosted **VT323 Regular** (32,084-byte WOFF2). Body/forms: existing
  **Inter Variable**. Code/metadata: local Cascadia Code/Consolas monospace stack.
  [Google Fonts metadata](https://github.com/google/fonts/blob/main/ofl/vt323/METADATA.pb)
  lists Vietnamese support; direct cmap validation also found every U+1EA0–U+1EF9
  glyph and the additional Vietnamese letters used by the page. Original TTF
  hash and conversion details are in `frontend/fonts/README.md`; OFL is bundled.
- Motion: feedback 140 ms, hover 200 ms, dialog/panel 260 ms, section reveal
  520 ms, hero entrance 640 ms with stagger capped at 260 ms. Only opacity and
  transform animate. No perpetual blink, canvas loop, scroll hijacking or new
  animation dependency. Entrance classes are removed after completion;
  IntersectionObserver unobserves each revealed section. Reduced motion disables
  animation. Content is visible without JavaScript or IntersectionObserver.
- All **364 pre-existing DOM IDs** are retained; eight landing IDs are added.
  `app.js` is unchanged. No backend, API, permission, game, database, runner,
  Compose or production settings change.
- Navbar/closing CTA buttons proxy `landing-login`/`landing-register`; a narrow
  MutationObserver mirrors the original disabled state. There is no second auth
  implementation. Section links stay outside the workspace hash router.
- Asset fingerprints cover the new stylesheet, SVG and binary font, across
  Windows CRLF and Linux LF. Existing HTML references in LAN/protocol docs are
  refreshed. Docker's existing frontend COPY includes these assets.
- The frontend release helper checks the additional static files. The runbook
  copies the complete frontend directory in its existing single image layer.
  Its backup, drain, Local/Remote pinning and rollback behavior is unchanged.
  No release or Docker operation was performed.

## Verification and local evidence

Run from the repository root with the existing development environment:

```powershell
.venv\Scripts\python.exe scripts/check_retro_landing_ui.py
.venv\Scripts\python.exe scripts/check_account_ui.py
node scripts/check_account_frontend_routing.cjs
.venv\Scripts\python.exe scripts/version_frontend.py --check
git diff --check
```

- Real Chrome/Playwright landing checks: 1440×1000, 768×1024, 390×844,
  360×800 and 320×760. No horizontal overflow, duplicate IDs or uncaught page
  errors; SVG and custom font load, one main landmark is visible.
- Keyboard menu/Tab/Escape/focus return, landing section links, navbar registration,
  closing login CTA, real disabled-registration server, failed bootstrap/retry,
  reduced motion and no-JavaScript readable fallback passed.
- Existing account browser suite passed: actual signup, Player/Admin login,
  role-specific navigation, session restoration, confirmed/failed logout,
  mobile drawer/focus/layout, session revocation, profile password confirmation,
  multi-tab logout and legacy API rejection. Its stale checks for the advanced
  menu and legacy rules in Player navigation were updated to the behavior already
  shipped in PRs #47/#48. The details focus cycle is still tested as Admin.
  The old checker failed at the same hidden-menu assertion on an archived copy
  of baseline `11a0711`, before this redesign.
- **127 pytest checks passed** (32.74 s; one existing Starlette/httpx deprecation
  warning): frontend auth/logout/Team contracts, account-only/auth HTTP, UX journeys,
  practice/monitoring, Docker homepage, content fingerprints and static release
  regressions. JUnit is stored in local evidence.
- Node syntax/routing/CSRF/stale-response checks and all frontend fingerprints pass.
- Chrome DevTools reports the custom VT323 font for the hero's Vietnamese text.
  Selected normal-text contrast pairs range from **4.73:1 to 16.29:1**. These
  measured pairs complement keyboard checks; they are not a complete WCAG audit.

Local evidence is intentionally excluded from Git and Docker builds in
`.qa-evidence/retro-pixel/`:

| Artifact | Purpose |
| --- | --- |
| `desktop.png`, `tablet.png`, `mobile.png` | Full landing captures |
| `small-mobile.png`, `minimum-mobile.png` | 360/320 px layouts |
| `mobile-registration.png` | Settled registration dialog |
| `browser-report.json` | Viewport and browser assertions |
| `font-coverage.json` | Font provenance and Vietnamese glyph validation |
| `contracts-and-contrast.json` | Preserved IDs and measured color pairs |
| `pytest.xml` | Focused regression results |

For a disposable visual preview, run
`python scripts/check_retro_landing_ui.py --serve --port 8876` and open
`http://127.0.0.1:8876`. It uses temporary data and test accounts, binds localhost,
and stops without touching the existing environment, uploads or database.

## Changed files

- Landing and shared presentation: `frontend/index.html`, `frontend/landing.css`,
  `frontend/styles.css`, `frontend/ui.js`.
- Assets: `frontend/art/arena-workstation.svg`, `frontend/fonts/VT323-Regular.woff2`,
  `frontend/fonts/VT323-OFL.txt`, `frontend/fonts/README.md`.
- Updated cache references: `frontend/lan.html`, `frontend/protocol.html`.
- Build/release compatibility: `scripts/version_frontend.py`,
  `scripts/arena_ui_release.py`, `docs/ARENA_SERVER_OPERATIONS.md`.
- Review and regression: `scripts/check_retro_landing_ui.py`,
  `scripts/check_account_ui.py`, `tests/test_arena_ui_release.py`,
  `tests/test_frontend_team_contract.py`, this document.

## Review boundary and next milestone

This milestone stops at a committed feature branch. It is not merged into main,
published or deployed to AWS. Browser evidence covers Chrome on Windows; Firefox,
Safari, actual phone hardware and a container/public-HTTPS acceptance run have not
been repeated for this visual change. The illustration is static by design.

After visual approval, adopt the same foundation in this order:

1. Player overview, Team/bot submission and tournament/Season discovery, retaining
   the existing task-based navigation and backend contracts.
2. Match/practice, standings and replay: prioritize data hierarchy and keep pixel
   type confined to headings rather than dense tables or engine rendering.
3. Admin operations: compact tables, readable semantic status, import/export,
   explicit destructive confirmation and Runner state. Keep the operational
   safety gates intact.
4. Extend keyboard/contrast and real browser journey coverage as each screen opts
   in; review desktop/mobile and reduced motion before proposing a release.

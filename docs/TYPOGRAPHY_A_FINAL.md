# Typography A — final implementation

The owner selected **Variant A / Refined Pixel**. It is integrated into the real
frontend on `feature/retro-pixel-ui-redesign`, following the comparison at
`2c2cc75`. Stop here for final visual review; do not merge main or deploy AWS.

## Typography decisions

- Hero, feature-section heading, workflow-section heading, closing CTA heading,
  decorative labels, brand and step numbers all use self-hosted **Handjet**.
  The mint line inherits the same face, size, weight and axes as the other hero
  lines. There is no modern/pixel font mixture within that headline.
- Weight **550**, `ELSH 2`, `ELGR 1`, with no synthesized bold. Hero letter spacing
  is −0.5 px; section headings use −0.8 px. The variable font retains all original
  glyphs, including Vietnamese NFC and NFD combining marks.
- Hero sizes/line heights: **94/88 px desktop**, **78/74 px tablet**, **76/74 px
  mobile**, **68/66 px at 320–360 px**. Section headings are 48 px desktop and
  44.16 px mobile with 1.26 line height. These follow the approved A comparison.
- The English brand and decorative step numbers now use Handjet too. VT323 stays
  as a historical asset with its license; no current CSS or preload uses it.
- **Feature-card titles remain Inter 600**, 22 px (19 px tablet, 20 px narrow
  mobile), with 1.4 line height. Actual desktop/mobile captures compared these
  against Handjet 34 px. Inter makes the longer Vietnamese phrases easier to scan
  and preserves the approved A card hierarchy; it does not interrupt the hero's
  single display face. Card links and descriptions remain Inter.
- Functional type follows the shared readability proposal: body 16 px desktop /
  15 px mobile; descriptions and CTA text 14 px; status/help 13 px; footer links
  13 px; illustration caption 12–13 px. Mobile CTAs stack to keep their text on
  one line. Form and account-dialog headings use Inter.
- Muted copy is `#B9B8B0`. Charcoal `#121212`, mint `#48D5AE`, cream `#F2EFE6`,
  illustration, section spacing, grid, motion durations and interactions retain
  the approved visual direction.

The Handjet file is **byte-identical to the approved A prototype**: 49,856 bytes,
WOFF2 SHA-256 `58b1a064748052179251a80a3d7ed9f27ba8a49bc3c26b2fcdd7bb0ebd1c6c0d`.
Provenance, original TTF hash, pinned Google Fonts revision, axes and bundled
SIL OFL 1.1 license are documented in [fonts/README](../frontend/fonts/README.md).

## Implementation and release compatibility

`frontend/tokens.css` now owns the shared display tokens and licensed font faces;
`frontend/landing.css` retains the approved responsive type rules. The subsequent
[workspace redesign](WORKSPACE_REDESIGN.md) preserves Variant A and extends its
foundation across the authenticated application.
`index.html` preloads Handjet instead of VT323. `version_frontend.py` fingerprints
Handjet in CSS and HTML using its unchanged binary bytes. The existing frontend
release verifier requires the new font **and its license**, in addition to the
other static files; the missing-asset regression includes both.

No backend, runner, database, Compose, deployment configuration, frontend auth
logic, DOM IDs, game rendering or API contracts changed. Inter and Handjet are
served locally, so the deployed frontend requires no font CDN.

The old A/B/C tool is explicitly historical. Its captures must be reproduced from
an isolated checkout at `2c2cc75`; a guard prevents overwriting its evidence with
the adopted frontend as a mislabeled baseline. The current review command is:

```powershell
.venv\Scripts\python.exe scripts/check_retro_landing_ui.py --output-dir .qa-evidence/typography-a-final
.venv\Scripts\python.exe scripts/check_account_ui.py
.venv\Scripts\python.exe scripts/version_frontend.py --check
```

## Executed verification

- **128 focused pytest checks passed**, one existing Starlette/httpx deprecation
  warning (61.70 s). Coverage includes auth/logout/Team contracts, account-only
  HTTP, UX journeys, practice/monitoring, Docker homepage, binary fingerprints
  and frontend release verification. JUnit is in the local evidence folder.
- Real Chrome: **1440×1000, 768×1024, 390×844, 360×800, 320×760**. No horizontal
  overflow, clipped text ranges, duplicate IDs, failed static/font requests or
  uncaught JavaScript errors. Extra checks around 640/641, 700, 900, 1024 and
  1100 px found no overflow. Hero and CTA wrapping were visually inspected.
- Chrome DevTools reports **only Handjet** for the actual hero, mint span and all
  major section headings, and Inter for the feature-card titles. A separate actual
  browser probe renders all requested Vietnamese phrases in both NFC and NFD
  with Handjet alone; no fallback face is used.
- The distributed WOFF2 cmap has zero missing characters in the Vietnamese
  U+1EA0–U+1EF9 block, additional Vietnamese letters and the NFC/NFD sample set.
- Keyboard menu, Tab/Escape/focus return, section links, navbar registration,
  closing CTA, failed bootstrap/reconnect, closed registration and readable no-JS
  fallback passed. Reduced motion produces no running landing animations.
- Existing account browser checks passed: real signup, Player/Admin login and
  role-specific navigation, session restore, failed/confirmed logout, mobile
  workspace focus/layout, revocation, profile password confirmation and multi-tab
  logout. They use temporary data, not the operational database.
- Direct comparison against approved A at 1440, 768, 390 and 320 px confirms the
  same Handjet binary, core palette and motion tokens. Desktop feature cards
  retain equal 333 px heights. The full desktop capture is still 1440×2288;
  mobile is 390×3396 versus the prototype's 390×3404, reflecting small brand,
  step-number and closing-heading refinements.

Local screenshots and reports are excluded from Git/Docker and retained at
`D:/LTM/.qa-evidence/typography-a-final/`:

- `desktop.png`, `tablet.png`, `mobile.png`, `small-mobile.png`, `minimum-mobile.png`.
- `*-hero.png`, `mobile-registration.png`, `vietnamese.png`.
- `browser-report.json`, `approval-comparison.json`, `pytest.xml`.

The feature-title alternatives are retained separately in
`.qa-evidence/typography-refinement/feature-titles-{inter,handjet}-{desktop,mobile}.png`.
The original approved `a-desktop.png` and `a-mobile.png` remain untouched there.

For an interactive review using temporary data, run
`python scripts/check_retro_landing_ui.py --serve --port 8878` and visit
`http://127.0.0.1:8878/`. This review covers Chrome on Windows, not Safari/Firefox
or physical devices. No AWS or production container operation was performed.

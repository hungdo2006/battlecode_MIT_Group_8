# NEON ARENA — Typography review A / B / C

Status: historical comparison at `2c2cc75`. **Variant A was subsequently selected
and integrated** on `feature/retro-pixel-ui-redesign`; see
[the final implementation and verification](TYPOGRAPHY_A_FINAL.md).
The screenshots below preserve the original comparison against `2d7173f`.

## View the comparisons

Generated local artifacts are in `D:/LTM/.qa-evidence/typography-refinement/`.
Open `index.html` for the original side-by-side board. To reproduce these historical
previews, use an isolated checkout at `2c2cc75` and run:

```powershell
.venv\Scripts\python.exe scripts/compare_landing_typography.py --serve --port 8877
```

Then visit `http://127.0.0.1:8877/__typography/`. The three interactive previews
are `/?typography=a`, `/?typography=b`, `/?typography=c`. The plain `/` route still
shows the original VT323 landing in that historical checkout. The tool refuses
to regenerate comparison evidence against the subsequently adopted frontend.
This is development tooling using temporary
data and localhost; no query-driven font switcher is added to the real app.

| Direction | Main type | Retro accents | Assessment |
| --- | --- | --- | --- |
| A — Refined Pixel (selected) | Handjet 550 for large headings; Inter for card titles/body/UI | Handjet labels; existing VT323 English brand and step numbers | Most visibly pixel-inspired. Slimmer and less dense than VT323, but still visibly stepped around Vietnamese marks. |
| B — Modern Retro Hybrid | Space Grotesk 600 for large headings; Inter for card titles/body/UI | Handjet 550 on “Đấu trí.” and selected decorative labels; existing brand/step numbers | Clear Vietnamese letterforms and a modern editorial hierarchy, with an intentional pixel accent. |
| C — Retro Monospace | IBM Plex Mono Medium 500 for large headings; Inter for card titles/body/UI | Existing VT323 English brand/step numbers only | Calm vintage-computer character and clear marks. Monospace takes more width and feels more technical than B. |

The 20–30% retro influence is a visual target rather than a measured font-usage
percentage. B confines it to the mint hero line, decorative labels and retained
brand details; functional text stays modern and readable.

## Shared refinements and fair comparison

All three use the **same content, charcoal/mint/cream colors, original computer
SVG, grid, section padding, navigation, feature cards, workflow, buttons and
motion tokens**. The browser audit compares content, core color tokens, artwork
URL and motion tokens with the baseline at each viewport.

Shared preview typography improves the existing small text:

- Inter body: 16 px desktop / 15 px mobile; feature/workflow descriptions 14 px.
- Navigation and CTAs: 14 px; status/help 13 px; illustration caption 12–13 px.
- Functional footer links: 13 px; decorative metadata 10–12 px. Labels using
  Handjet are 16–18 px rather than tiny pixel text.
- Feature titles: Inter 600, 22 px (19 px tablet); comfortable 1.4 line height.
- Muted text: `#B9B8B0`, brighter than baseline `#AAA9A2`; cream card text stays
  `#555A50`. Primary backgrounds, cream, mint, illustration and borders are intact.
- CTA controls stack consistently on mobile so larger functional type fits
  without breaking the button text. This common adjustment applies to A/B/C.
- No decorative font is used for inputs or paragraphs. Account-dialog titles
  use Inter in all three previews.

Nominal display sizes are optically matched instead of assuming that different
fonts at the same CSS size have equal visual height:

| Context | A — Handjet | B — Space Grotesk | C — IBM Plex Mono |
| --- | --- | --- | --- |
| Desktop hero | 94 px | 72 px | 68 px |
| Tablet hero | 78 px | 60 px | 52 px |
| 390 px hero | 76 px | 56 px | 52 px |
| 320 px hero | 68 px | 48 px | 44 px |
| Desktop section headings | 48 px | 38 px | 35 px |

The three hero line boxes share 88 px desktop, 74 px tablet/mobile and 66 px at
320 px; all keep the original three-line heading. B's pixel accent is 1.28 times
its normal hero font size to match the perceived height. Normal text reflows
according to each face's actual metrics; no content is hidden to equalize images.

## Fonts, Vietnamese and licenses

Only self-hosted review assets are used; no browser font CDN requests are needed.
All candidates are distributed under **SIL Open Font License 1.1**, with their
original license files beside the generated WOFF2 files.

| Asset | Author / source | WOFF2 | Local license |
| --- | --- | --- | --- |
| Handjet | Rosetta, David Březina; [Google Fonts metadata](https://github.com/google/fonts/blob/main/ofl/handjet/METADATA.pb) | 49,856 bytes | `fonts/Handjet-OFL.txt` |
| Space Grotesk | Florian Karsten; [Google Fonts metadata](https://github.com/google/fonts/blob/main/ofl/spacegrotesk/METADATA.pb) | 49,232 bytes | `fonts/SpaceGrotesk-OFL.txt` |
| IBM Plex Mono | Mike Abbink / Bold Monday, IBM; [Google Fonts metadata](https://github.com/google/fonts/blob/main/ofl/ibmplexmono/METADATA.pb) | 40,140 bytes | `fonts/IBMPlexMono-OFL.txt` |

Inter and the small retained VT323 accents use the existing bundled OFL assets.
New fonts are not copied into `frontend/` or the production build.

Sources were pinned to Google Fonts revision
`e7db6ca603fd4862010383ff17ffd6cc4ffac1c0`; original SHA-256 digests, variable axes,
license information and missing-glyph lists are in local `font-coverage.json`.
The WOFF2 files preserve the full original glyph sets and font names.

Pixelify Sans was evaluated and rejected: the actual font lacks **95 characters**
in the combined test set (Vietnamese block U+1EA0–U+1EF9, additional Vietnamese
letters and the requested sample text in NFC/NFD). Mixing fallback glyphs into
large Vietnamese headings would give the uneven accents this review should fix.

Handjet, Space Grotesk and IBM Plex Mono have **zero missing characters** in that
same test set. Browser checks additionally inspect actual Chrome platform fonts
for the hero and every requested Vietnamese phrase, including decomposed marks.
This verifies real rendering rather than relying on a font's language label.

To reproduce font preparation, install fontTools/Brotli only in a local tool
directory or use the existing review tooling environment, then run:

```powershell
.venv\Scripts\python.exe -m pip install --target .qa-evidence/typography-refinement/font-tools fonttools brotli
.venv\Scripts\python.exe scripts/compare_landing_typography.py --prepare-fonts
.venv\Scripts\python.exe scripts/compare_landing_typography.py --capture
```

`--prepare-fonts` retrieves the current Google Fonts revision and records its
exact SHA and file hashes, so a future refresh may be a different documented
revision. Existing local assets reproduce this review without network access.

## Screenshots and verification

Each variant and the unchanged baseline has actual Chrome captures at
**1440×1000, 768×1024, 390×844 and 320×760**. Full-page captures include hero,
feature cards, workflow, closing CTA and footer; `*-hero.png` captures are extra
crops from the same browser render.

| Variant | Desktop | Mobile | Narrow mobile |
| --- | --- | --- | --- |
| Baseline | `baseline-desktop.png` | `baseline-mobile.png` | `baseline-narrow-mobile.png` |
| A | `a-desktop.png` | `a-mobile.png` | `a-narrow-mobile.png` |
| B | `b-desktop.png` | `b-mobile.png` | `b-narrow-mobile.png` |
| C | `c-desktop.png` | `c-mobile.png` | `c-narrow-mobile.png` |

The generated `browser-report.json` records viewport geometry, text ranges,
loaded custom fonts, card heights, functional text sizes, colors, motion tokens,
font/API failures and application checks. Each variant uses fresh temporary data
and unchanged default rate limits; the audit does not weaken auth settings to
accommodate synthetic browsing volume.

Executed results:

- **16/16 layouts passed**: no horizontal overflow, off-screen text ranges or
  duplicate IDs; equal desktop feature-card heights (333 px in A/B/C).
- Custom-font inspection passed for actual hero text and all requested Vietnamese
  phrases in NFC and NFD. B correctly uses both Space Grotesk and Handjet in the
  hero; the other faces do not fall back to unrelated fonts.
- A/B/C each passed real registration, Player login, restored session after reload,
  logout, Admin login with role-specific visibility, and Admin logout.
- Mobile keyboard menu, Tab/Escape/focus return and reduced motion passed in each.
- Zero uncaught JavaScript errors, failed static/font requests or HTTP 429/5xx
  API responses in the completed audit. Normal anonymous auth probes return 401.
- Baseline frontend and backend/runner/deployment files have no diff against
  `2d7173f`; the existing asset-version check still passes.
- `comparison-board.png` is a browser capture of the local review board; all six
  screenshot thumbnails load, all three variants are present, and the board has
  no horizontal overflow. The full landing screenshots remain the authoritative
  comparisons for hero, feature cards and workflow.

Review boundary: this validates Chrome on Windows and local account workflows.
It is not a full assistive-technology, Firefox/Safari or production deployment
acceptance test. Font size and weight choices remain proposals. After visual
approval, adopt only the chosen family and scopes, then update fingerprints and
the existing release checks as a separate implementation change.

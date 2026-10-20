# NEON ARENA — Premium Monochrome

The current frontend design follows only [Resend](https://resend.com/) and
[shadcn/ui](https://ui.shadcn.com/examples/dashboard). This direction supersedes
the historical Liquid Glass briefs. Vercel Geist and Linear are not design
references for this implementation.

## Foundations

The public landing and application share the same neutral palette, controls,
spacing and surface rules. The landing uses editorial typography and more
whitespace; application screens prioritize tasks and real data.

| Token | Value |
| --- | --- |
| Background / surface | #ffffff |
| Supporting surfaces | #fafafa, #f5f5f5 |
| Primary text / action | #171717 |
| Secondary text | #666666 |
| Dividers / panel borders | #e5e5e5 |
| Input border | #8f8f8f |
| UI font | Self-hosted Inter Variable |
| Landing headline | Self-hosted Source Serif 4 Variable |
| Code and match IDs | System monospace |
| Control / panel / dialog radius | 8 / 12 / 16px |
| Spacing | 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 / 96px |
| Control height | 40px desktop; at least 44px mobile |
| Sidebar / topbar | 240 / 64px desktop |

Source Serif 4 replaces the proposed system Georgia font because browser review
showed inconsistent Vietnamese glyph fallback. Font sources and SIL Open Font
License files are included in frontend/fonts/. The app makes no font CDN
requests and requires no new JavaScript framework.

Use whitespace and dividers before introducing another card. Surfaces are
opaque: no gradients, reflections, blur or decorative glow. Shadows are limited
to transient layers such as dialogs and toasts. Semantic color remains available
for errors, warnings and confirmations, accompanied by labels.

## Components and navigation

- Black primary buttons, bordered secondary buttons and text actions share the
  same sizing and focus styles.
- Typography uses Inter 400/500/600; task titles are 28px desktop and 24px mobile.
  The public landing has the only serif headline.
- Lists, standings, tournament fixtures and brackets use neutral borders,
  restrained badges and readable rows. Numeric data uses tabular numerals.
- Desktop navigation sits against the left edge. Below 1024px the same DOM tree
  becomes a labelled drawer with keyboard containment, Escape/backdrop dismissal,
  focus restoration and an inert background.
- Below 768px forms become one column and inputs use 16px type. Tables, brackets
  and code scroll within their own regions instead of overflowing the page.
- Motion is brief and optional via prefers-reduced-motion. Visible focus,
  native dialogs, live status announcements and existing permission visibility
  remain in place.

## Game presentation

Robot Battle and OTT v2 use a neutral board and distinguish side A with dark
filled pieces and side B with light outlined pieces. A/B labels, piece shapes,
coordinates, goals and event descriptions remain available. Changes are visual;
board geometry, rules, frames and replay data are unchanged.

## Implementation boundaries

Routes and DOM bindings remain compatible. Team management still lives in
#upload, and the shared Canvas/replay player still lives in #home. Legacy and
Account-Only navigation remain distinct according to the existing permissions.
Direct Official Match links resolve after the server's authentication mode has
loaded. Backend, API payloads, authentication, CSRF, simulation, WebSocket and
Official polling logic are unchanged.

Run these checks after frontend changes:

    python scripts/version_frontend.py
    python scripts/version_frontend.py --check
    node --check frontend/app.js
    node --check frontend/renderers.js
    node scripts/check_account_frontend_routing.cjs
    python scripts/check_account_ui.py
    python -m pytest tests controller_tests -ra

The Account UI checker owns disposable data and verifies the mobile drawer.
scripts/check_multiplayer_ui.py exercises three independent Chrome sessions,
actual sample submissions, invitations, live frames, reconnect and saved replays.
Use an isolated QA server when supplying its --url option.

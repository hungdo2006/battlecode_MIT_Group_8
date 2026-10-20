# NEON ARENA — Premium Monochrome

The active visual references are [Resend](https://resend.com/) and
[shadcn/ui](https://ui.shadcn.com/examples/dashboard). Historical Liquid Glass
briefs are superseded. Vercel Geist and Linear are excluded as references.

## Foundations

The landing and workspace share neutral colors, typography, spacing and controls.
The landing uses a two-column composition: a Vietnamese headline and clear entry
actions beside an explicitly labelled bot-code example. The example demonstrates
Robot Battle's JSON protocol; Battlecode has its own API and upload instructions.

| Token | Value |
| --- | --- |
| Background / surface | #ffffff |
| Supporting surfaces | #fafafa, #f5f5f5 |
| Primary text / action | #171717 |
| Secondary text | #666666 |
| Dividers / panel borders | #e5e5e5 |
| Input border | #8f8f8f |
| UI and landing headline | Self-hosted Inter Variable, including Vietnamese |
| Code and match IDs | System monospace |
| Control / panel / dialog radius | 8 / 12 / 16px |
| Spacing | 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 / 96px |
| Control height | 40px desktop; at least 44px mobile |
| Sidebar / topbar | 240 / 64px desktop |

The headline now uses Inter, avoiding mixed headline font families. The reported
missing-glyph appearance was not reproduced exactly in the initial local review;
the browser did load the old Source Serif font. We do not attribute that screenshot
to a proven font-file failure. Font files, CSS and JavaScript now have
content-based URL fingerprints to prevent stale asset combinations after updates.
No external font CDN is required. Font licenses remain in `frontend/fonts/`.

Use whitespace and dividers before introducing another card. Opaque surfaces,
restrained borders, and readable rows take priority over decoration. Semantic
colors accompany status labels; shadows are reserved for transient layers.

## Layout and motion

- One role-aware sidebar becomes a modal drawer below 1024px. It contains focus,
  closes with Escape/backdrop/selection, restores focus and makes the workspace inert.
- Forms become one column below 768px with 16px input text. Tables, code and
  brackets scroll inside their regions. Upload is sticky on wide screens.
- Landing elements enter in a short sequence. Page changes, buttons and arrows
  have subtle transitions and press feedback. `prefers-reduced-motion` disables
  movement and smooth scrolling.
- Visible keyboard focus, native dialogs, live feedback, disabled pending actions,
  compiler diagnostics and meaningful empty states are shared component patterns.

## Page plan implemented

| Page | Primary task and composition |
| --- | --- |
| Landing | Headline, login/register, labelled code sample, three-step workflow |
| Overview | Real team, Active Bot, official schedule and account match statistics; arena appears when a match is opened |
| Team & Bot | Team lifecycle/members, game-specific upload protocol, versions, compile logs, Active Bot selection |
| Scrimmage | Eligibility, game/opponent, durable queue, cancellation, result and scoped replay |
| Official schedule | Bot lock/start times, status, replay; Admin schedule and verification controls |
| Seasons | Registration timeline/capacity, Captain registration, Admin roster freeze and champion publication |
| Tournaments | Existing formats, fixtures, groups, brackets and advancement |
| Standings | Per-game tournament/group results; elimination progress remains in brackets |
| History & Replay | Player Scrimmage history; Official replays also open from the official schedule |
| Rules & Samples | Installed games, rules form, source links, API guides and starter downloads |
| Profile | Display name editing; username and system role remain controlled by authentication |
| Accounts, Admin | Search, team/role/status, Player enable/disable, invitations and account recovery |
| System, Admin | Actual runner readiness, toolchains, queue counts, active matches and interruptions |

Robot Battle, OTT v2 and Battlecode use a neutral Canvas and distinguish dark A
from outlined/light B using labels and shapes. Battlecode frames come from the
official engine's replay; its raw `.bc26` file is available separately.

Legacy LAN and Account-Only authorization remain distinct. New backend features
are documented in [Battlecode integration](BATTLECODE_2026.md) and the
[acceptance matrix](FEATURE_ACCEPTANCE.md).

## Verification

```text
.venv\Scripts\python.exe scripts/version_frontend.py --check
node --check frontend/app.js
node --check frontend/renderers.js
node scripts/check_account_frontend_routing.cjs
.venv\Scripts\python.exe scripts/check_account_ui.py
.venv\Scripts\python.exe -m pytest tests controller_tests -ra
```

The browser checker owns disposable account data and verifies authentication,
role gating, responsive navigation, focus restoration and mobile overflow.

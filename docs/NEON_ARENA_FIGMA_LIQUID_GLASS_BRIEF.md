# NEON ARENA — Figma-informed Liquid Glass Design Brief

**Purpose:** A practical visual-design specification for Codex to implement in the existing `feature/product-polish` branch **without needing Figma MCP access**.

**Project:** NEON ARENA (FastAPI + plain HTML/CSS/JavaScript + Canvas + WebSocket; Robot Battle and OTT v2; Docker Bot Sandbox).

## 1. Source evidence and limitations

Figma design reference: https://www.figma.com/design/QLGOIP3ncS6kWTQt0LImTL/Liquid-Glass-UI-%7C-Apple-IOS-26--WWDC25---Community-?node-id=0-1

Related Community listing shared by owner: https://www.figma.com/community/file/1514237154489556536

Inspected **via Figma MCP in ChatGPT**:
- Top-level document metadata: one page, `0:1` **🖼️ Cover**.
- Cover frame: `1:637`, **1920 × 1080**.
- Cover structure: headline group (`3:6`) and two rounded-rectangle image layers (`1:700`, `1:701`).
- Rendered cover screenshot examined visually.
- Variable definitions queried for cover: `{}` (none returned).

**Observed, not guessed:** The cover shows a large pastel-gradient “Liquid Glass / iOS 26” title on a soft light gray backdrop and two iPhone examples. One has green photographic foliage wallpaper with a dark translucent, rounded floating media-control surface. The other has a light music-app interface with rounded content/media cards and a frosted, pill-like bottom navigation layer. The overall treatment emphasizes translucency, rounded geometry, surface depth, and content remaining visible through glass.

**Limits:** This accessible file does **not** expose a full reusable dashboard component library, documented variable palette, numeric blur values, typography tokens, or desktop-specific layouts. No exact values in section 3 should be represented as extracted Figma tokens. The Community listing's full contents have not been separately inspected here. The Figma reference is predominantly **mobile music UI**, not a desktop tournament dashboard.

## 2. Design goal

Retain the existing NEON ARENA **light desktop-first application**, functionality, content hierarchy, and identity, while giving selected surfaces more convincing, refined Liquid Glass material behavior.

Visual principles adapted from the observed Figma cover:
1. **Layered transparency**: glass belongs on a meaningful foreground layer, with a subtle background visible through it.
2. **Soft geometry**: rounded surfaces and continuous-feeling corners; no heavy neon borders.
3. **Clarity first**: text and critical controls should remain readable; opaque/light solid cards where data is dense.
4. **Purposeful elevation**: floating sidebar, modal, invitation toast, replay controls; minimal decorative blur.
5. **Confident restraint**: blue accent already used in NEON ARENA, neutral text, a tiny amount of pastel light; no indiscriminate multicolor gradient text.

## 3. Proposed implementation tokens (NOT extracted from Figma)

These are starting recommendations for Codex to refine against the current CSS and browser screenshots. They are **project-specific design proposals**, not Figma measurements.

```css
:root {
  --app-bg: #f4f7fc;
  --text-primary: #172238;
  --text-secondary: #596b85;
  --accent-primary: #2e6be6;
  --accent-soft: #eaf1ff;

  --glass-bg: rgba(255, 255, 255, 0.68);
  --glass-bg-elevated: rgba(255, 255, 255, 0.82);
  --glass-stroke: rgba(255, 255, 255, 0.85);
  --glass-inner-stroke: rgba(78, 111, 166, 0.10);
  --glass-blur: 18px;
  --glass-saturate: 145%;
  --glass-shadow: 0 14px 38px rgba(49, 76, 128, 0.10);

  --surface-solid: #ffffff;
  --border-subtle: rgba(87, 114, 157, 0.15);
  --radius-control: 13px;
  --radius-card: 22px;
  --radius-floating: 26px;
  --motion-fast: 160ms;
  --motion-medium: 240ms;
}

.glass-surface {
  background: var(--glass-bg);
  border: 1px solid var(--glass-stroke);
  box-shadow: var(--glass-shadow), inset 0 1px 0 rgba(255,255,255,0.75);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
  backdrop-filter: blur(var(--glass-blur)) saturate(var(--glass-saturate));
}

@supports not (backdrop-filter: blur(1px)) {
  .glass-surface { background: rgba(255, 255, 255, 0.94); }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

**Guidance:** Match existing CSS conventions and use the minimum required tokens. Test contrast and legibility with actual screenshot evidence. Do not apply `.glass-surface` indiscriminately to every panel. Keep opaque backgrounds behind long text, submission diagnostics, large tables and Canvas game boards.

## 4. Apply to the actual NEON ARENA screens

| Surface | Visual treatment | Preserve |
| --- | --- | --- |
| App shell and sidebar | Floating pale glass sidebar, soft rim lighting, clear active nav indicator, restrained shadow | Navigation IDs, responsive behavior, session controls |
| Overview | Existing light layout; depth via a few layered cards and subtle luminous background | Competition state, game info, CTAs |
| Organizer controls | Solid form fields inside premium panels; elevated confirmation modal; unambiguous OPEN/SETUP/DRAINING badges | Auth, game lock, rules, invitations |
| Bot submission | Clear, mostly opaque upload/compile surface; light glass around outer card; legible error log | Input, compile state, Active Bot, file restrictions |
| Player lobby | Floating invitation popover and elevated player cards; readable online/ready statuses | Presence, Accept/Decline and reconnect |
| Live Arena | Mostly opaque game-board stage, minimal glass framing; floating player names/status where readable | Canvas, simulation events, WebSocket |
| Replay | Frosted floating transport bar and timeline controls; strong focus/hover states | Seek/play/pause/speed/download |

### Priorities

**P0:** No functionality regression; no change to FastAPI/WS/Game Adapter/Sandbox; no secret leaks.

**P1:** Consistent transparent surfaces and depth on sidebar, header, overview cards, modals; clearer active/disabled/focus states.

**P2:** Compact, refined replay bar and invitation popup; subtle pointer/hover interactions, responsive polish.

**Avoid:** Direct copying of iOS status bars, music app layout, Apple brand assets, proprietary photos, or the mobile bottom tab bar on desktop.

## 5. Implementation and verification contract for Codex

1. Check out `feature/product-polish`, confirm changes before touching files, inspect existing frontend and event handlers.
2. Treat this Markdown as a **source-informed design brief**; do not claim to have queried Figma MCP yourself.
3. Preserve current light UI; refine through targeted reusable styles and limited markup changes.
4. Preserve all existing functions and dynamic bindings for Organizer, Player, Bot Submission, Lobby, Invitation, Live Arena and Replay.
5. Avoid frameworks/new large dependencies; use CSS variables and existing vanilla JS.
6. Use actual browser verification at 1440×900, 1366×768, and one narrower viewport; check shell, Organizer, Bot Submission, Lobby, Live Arena and Replay.
7. Run relevant tests, report exact commands/results, and show **real** screenshots if possible.
8. Confirm Docker-served assets are fresh; handle stale CSS/JS caching with sensible asset versioning/headers rather than relying on incognito mode.
9. Keep `.env` and sandbox credentials out of git and out of browser source.
10. **Do not commit, push, or merge** until the owner reviews.

## 6. Definition of done

- Visibly closer to *layered, subtly translucent Liquid Glass* than the prior flat-light dashboard.
- Strong readability, keyboard focus, meaningful loading/error/disabled states, reduced-motion support.
- Preserve desktop navigation and core tournament flows; no mock data replacing live state.
- Compare before/after browser screenshots of the actual application.
- Figma observations and authored adaptations are distinguished in the final report.

---

**Evidence provenance:** Figma MCP metadata and screenshot for `0:1` / `1:637`, plus variable-definition query yielding `{}`. Implementation palette/measurements in this document are proposals, not confirmed Figma design tokens.

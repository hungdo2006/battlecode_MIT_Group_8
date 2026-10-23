# Sandbox artifact compatibility

**Issue:** A bot compiled against an old Docker sandbox image could still be shown as `ready`, but the Controller rejects the artifact when the match begins (`Artifact/toolchain mismatch`). This interrupted scrimmages without a winner.

**Fix:** The private Controller advertises its *pinned image ID* (normal and optional Battlecode image). The Arena keeps this current across controller restarts, and compares it to the image ID already stored with every compiled bot. The check is used by bot library / active selection, scrimmage eligibility and challenge creation, official bot lock and dispatch, and match launch.

Outdated bots are displayed as **Cần biên dịch lại**, excluded from eligible practice opponents, and cannot be selected or dispatched. Teams must submit their source again and choose the newly compiled bot. Compile status, stored source/artifacts, historical requests and replay are never modified. There is no database migration. Legacy artifacts without the image metadata are fail-closed on the active Sandbox; historical replay is still available.

The Controller keeps verifying artifact integrity and image at runtime, so the preflight is additional defense rather than a weakened runtime check. If the Controller is unavailable or lacks an image identity, admission is denied instead of guessing.

## QA checklist

- Current image bot: `ready`, selectable and runnable.
- Historical image bot: `needs_rebuild`, selection rejected, team/practice readiness false, omitted from opponent list.
- Changing game uses the correct pinned engine image (including optional Battlecode 2026).
- Official lock and scheduled dispatch block stale bots without scoring a loss.
- Old source and replay remain accessible. Re-upload + select new bot works.
- Controller restart and image change update the identity; disconnection fails closed.
- On AWS, keep Sandbox image stable while updating Arena and Controller; don't rebuild `bot-image` as part of this deploy.

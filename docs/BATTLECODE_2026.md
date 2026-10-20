# Battlecode 2026 and asynchronous Scrimmage

## Engine provenance

This integration runs the official [MIT Battlecode 2026 source](https://github.com/battlecode/battlecode26/tree/103abf6b67a2cf544e6344dddef9318af9ae9193),
pinned to commit `103abf6b67a2cf544e6344dddef9318af9ae9193`. The source archive SHA-256
is `bb0bab34c26a60d423bbb5d1a0e55ab28d9ee31a76780ef314161c41b4ffc696`.
It is built from source, rather than described as a particular published release.
The upstream repository and its license/attribution files are retained in the build stage.

Java 21 executes the official headless engine. Python 3.12 runs its official
crossplay bridge. NEON ARENA does not replace the rules or approximate a match
using Robot Battle. `ArenaReplay.java` reads the official gzip/FlatBuffers replay
and exports browser frames. The original `.bc26` remains available for the official
Battlecode client. The browser presentation is a compact viewer, not the full
official client's debugger or profiler.

## Enable on a Docker deployment

After the normal [sandbox setup](SANDBOX.md), use:

```sh
docker compose -f compose.yaml -f compose.battlecode.yaml up -d --build --wait
```

The override builds `neon-arena-battlecode:2026`, enables `ARENA_BATTLECODE26=1`
in the backend and configures `BATTLECODE_IMAGE` in the private controller.
The default Compose deployment continues to install Robot Battle and OTT v2.
Include the override on subsequent Compose commands for this deployment.
Building the image requires access to upstream source and dependency registries.
Native execution cannot run Battlecode or asynchronous Scrimmage.

Back up existing persistent data before updating and follow the
[operator handover](PHASE_4_3_OPERATOR_HANDOVER.md). Account migrations 16 and 17
append Scrimmage and season tables; existing teams, ownership and source
attestations are preserved. Switching engine images invalidates old engine-bound
compile receipts: resubmit bots against the new image before competing.

## Bot formats and rules

Upload **one UTF-8 source file, 1–256 KiB**:

| Language | Required entrypoint | Starter |
| --- | --- | --- |
| Python 3.12 | Top-level `def turn():`, no parameters; official API globals include `rc` and `Direction` | `samples/battlecode26/bot.py` |
| Java 21 | `package arena; public class RobotPlayer` and `public static void run(RobotController rc)` | `samples/battlecode26/RobotPlayer.java` |

Java may declare `throws GameActionException`. The adapter validates the compiled
class and method signature. C++, multi-file ZIP projects and custom uploaded maps
are not supported by this integration. Available official maps are `DefaultSmall`,
`DefaultMedium` and `DefaultLarge`; choose one in the existing rules form.
Battlecode does not use the JSON-stdin/stdout protocol of Robot Battle or OTT v2.
Compilation validates the entrypoint and syntax; normal runtime behavior remains
the responsibility of the bot and official engine.

## Execution and replay

The backend has no Docker socket. It sends fixed, lease-authenticated jobs to the
private controller, which binds source receipts to source digest and image ID.
Callers cannot supply container commands, paths or Docker options.

Each Battlecode container runs as UID/GID 10001, without network access, with a
read-only root filesystem, dropped capabilities and no new privileges. Its limits
are 1 GiB memory, 2 CPUs, 256 PIDs, 256 MiB work tmpfs and 64 MiB temporary tmpfs.
The supervised engine timeout is 150 seconds, with a separate 20-second replay
export timeout. Oversized/unfinished replays and infrastructure failures interrupt
the job; they are not silently converted into a bot loss. The compact exported
replay is capped at 12 MiB and decompression at 64 MiB.

Participants and Admin may download JSON replay and raw `.bc26` via the
audience-scoped Official/Scrimmage endpoints. Other teams receive 404. Opponent
source and controller artifacts are not exposed.

## Scrimmage and seasons

An active Team member selects an installed game and an opponent with an attested,
ready Active Bot. Sending a challenge freezes both bot versions and rules. The
server executes it even after both players log out. Per requesting Team, at most
three jobs may be pending; duplicate pending ordered pairs/game are rejected and
the global waiting queue is capped at 100. The challenger or Admin can cancel a
queued request. Official scheduling has dispatch priority over practice within
the shared two-match capacity.

The queue persists in SQLite. After an uncertain backend restart, previously
claimed work is marked interrupted rather than automatically running twice.
Scrimmage results do not modify Official tournament rankings.

Admin creates season registration/start/end dates and capacity. An active Team's
Captain registers or withdraws during the enforced registration window. Admin
closes registration and atomically freezes registered teams into an existing
tournament format. Season start/end fields describe the planned event; fixture
bot-lock and scheduled-start times control actual execution. There is no automatic
hard shutdown at the season end date. Publication requires a completed, verified
tournament, derives its champion from the result, and stores an audit snapshot.

## Reproducible acceptance

```text
docker build -f integrations/battlecode26/Dockerfile -t neon-arena-battlecode:2026 .
.venv\Scripts\python.exe scripts/check_battlecode_engine.py
.venv\Scripts\python.exe scripts/check_battlecode_platform.py
```

The first checker runs actual Java/Java, Python/Java, Python/Python matches,
entrypoint rejection, published starter APIs and replay decoding. The second
creates an isolated Compose project, disposable accounts and teams, checks offline
Scrimmage, private replay, a complete official season, profile/account controls,
and Robot Battle/OTT regression. It removes only its own resources on completion.
`--serve` retains this disposable review deployment; stop with Ctrl+C or the
task-owned `design-research/battlecode26-engine/stop-platform-review` marker.
Local browser fixture credentials are temporary and must not be committed.

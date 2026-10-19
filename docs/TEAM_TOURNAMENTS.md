# Account-Only Team tournaments

This first Team tournament release adds round-robin competitions to the Account-Only workflow. It is separate from the legacy Player tournament records.

## Rules

- Admin creates a tournament with 2–16 distinct ACTIVE Teams and an installed game.
- Starting the tournament snapshots the participating Team names and generates one fixture for every pair.
- Admin schedules each fixture individually. Scheduling creates an Official Match request in the same SQLite transaction that links the request to its fixture.
- Official Match retains the existing bot lock deadline, source/artifact checks, sandbox execution, result verification and replay access rules.
- Active members of participating Teams can read the tournament, standings and fixture status. Admin can read all Team tournaments.
- Standings award 3 points for a win, 1 for a draw and 0 for a loss; ties are ordered by wins and then Team name.

The first release does not include elimination brackets, automatic date generation, tournament cancellation, public Player standings, or standings based on score difference. An Official Match that is blocked, interrupted or cancelled does not count as a completed fixture.

## Account-Only API

- `GET /api/admin/team-tournaments`
- `POST /api/admin/team-tournaments`
- `GET /api/admin/team-tournaments/{id}`
- `POST /api/admin/team-tournaments/{id}/start`
- `POST /api/admin/team-tournaments/{id}/fixtures/{fixture_id}/schedule`
- `GET /api/player/team-tournaments`
- `GET /api/player/team-tournaments/{id}`

Mutating routes require the existing Admin audience cookie and CSRF protection. The Player routes are scoped to a current membership in one of the tournament Teams.

## Database migration

SQLite migration v10 is append-only. Back up and rehearse on a disposable copy before applying it to an existing installation. For an offline migration, stop the backend and run:

```powershell
python -m backend.admin_cli --data-dir <disposable-data-dir> migrate
python -m backend.admin_cli --data-dir <disposable-data-dir> check
```

Do not migrate a production volume as part of local feature development.

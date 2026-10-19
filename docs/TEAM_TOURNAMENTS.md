# Account-Only Team tournaments

Team tournaments in the Account-Only workflow are separate from the legacy Player tournament records. Supported formats are round-robin, single elimination, double elimination, group stage followed by single elimination, and Swiss stage followed by single elimination.

## Rules

- Admin creates a tournament with 2–16 distinct ACTIVE Teams and an installed game. Group stage plus knockout requires at least four Teams.
- Starting a round-robin tournament generates every pair. Single elimination creates a bracket and grants automatic byes when needed.
- Double elimination creates winners and losers brackets. A Team is eliminated after its second loss. The grand final pits both bracket champions against each other; a reset final is scheduled only if the losers-bracket champion wins the first grand final.
- Group stage plus knockout creates two groups for 4–8 Teams or four groups for 9–16 Teams, distributes Teams in the order selected at creation, and generates round-robin fixtures inside each group. The top two from each group advance; cross-pairings are A1–B2 and B1–A2 (and C/D equivalents when there are four groups).
- Swiss stage plus knockout requires 4–16 Teams. It runs three rounds for 4–8 Teams and four rounds for 9–16 Teams. After each round, Teams are paired by standings and rematches are avoided when a valid pairing exists. An odd field gives one bye point to the lowest-ranked Team that has not received a bye. Swiss standings award 1 point for a win, 0.5 for a draw and 0 for a loss; ties are ordered by Buchholz, score difference, score, wins and Team name. The top four qualify when there are 4–7 Teams; the top eight qualify when there are 8–16 Teams, seeded into single elimination.
- Admin schedules each fixture individually. Scheduling creates an Official Match request in the same SQLite transaction that links the request to its fixture.
- Official Match retains the existing bot lock deadline, source/artifact checks, sandbox execution, result verification and replay access rules.
- Active members of participating Teams can read the tournament, standings and fixture status. Admin can read all Team tournaments.
- Group standings award 3 points for a win, 1 for a draw and 0 for a loss; ties are ordered by points, score difference, score, wins and then Team name. Swiss standings are separate and use their own point scale and Buchholz tiebreaker. The free-play Player leaderboard keeps its original meaning and remains separate from Team tournament tables.
- In knockout fixtures, a draw automatically schedules a rematch with bots locked immediately and a one-minute start delay. The system allows three official attempts for a fixture; if all three draw, Admin must select which Team advances. That decision is audited.

The first release does not include automatic date generation or tournament cancellation. An Official Match that is blocked, interrupted or cancelled does not count as a completed fixture.

## Account-Only API

- `GET /api/admin/team-tournaments`
- `POST /api/admin/team-tournaments`
- `GET /api/admin/team-tournaments/{id}`
- `POST /api/admin/team-tournaments/{id}/start`
- `POST /api/admin/team-tournaments/{id}/fixtures/{fixture_id}/schedule`
- `POST /api/admin/team-tournaments/{id}/fixtures/{fixture_id}/resolve-tie`
- `GET /api/player/team-tournaments`
- `GET /api/player/team-tournaments/{id}`

Mutating routes require the existing Admin audience cookie and CSRF protection. The Player routes are scoped to a current membership in one of the tournament Teams.

## Database migration

SQLite migrations v10–v14 are append-only. Back up and rehearse on a disposable copy before applying them to an existing installation. For an offline migration, stop the backend and run:

```powershell
python -m backend.admin_cli --data-dir <disposable-data-dir> migrate
python -m backend.admin_cli --data-dir <disposable-data-dir> check
```

Do not migrate a production volume as part of local feature development.

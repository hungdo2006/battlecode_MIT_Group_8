# NEON ARENA

**NEON ARENA** is a self-hosted platform for competitive programming with autonomous bots. Players submit code, teams compete in scheduled matches, and organizers manage tournaments through a web interface.

## Highlights

- **Multi-game support:** Robot Battle and OTT v2, with an extensible game-adapter architecture.
- **Bot submissions:** Python, C++, and Java, compiled and executed through a Docker-based sandbox.
- **Team competitions:** Team management, active bots, scheduled official matches, and multiple tournament formats.
- **Live experience:** Match visualization, results, history, and replay.
- **Role-based access:** Player and Admin workflows in the optional Account-Only mode.

## Tech stack

| Layer | Technologies |
| --- | --- |
| Frontend | HTML, CSS, JavaScript, Canvas |
| Backend | Python, FastAPI, REST, WebSocket |
| Data | SQLite, JSON/JSONL replays |
| Runtime | Docker Compose, isolated bot containers |
| HTTPS gateway | Caddy (separately configured) |

## Run locally

**Requirements:** Docker Engine/Desktop with Linux containers, Docker Compose v2, and Python 3 for the configuration helper.

1. Create private local configuration:

   ```bash
   python3 scripts/configure_sandbox.py
   ```

   On Windows, use `py -3 scripts/configure_sandbox.py`. The script creates or completes `.env` without printing credentials. To restrict access to your own machine, set `ARENA_BIND_IP=127.0.0.1` in `.env` before starting.

2. Build and start the services:

   ```bash
   docker compose up -d --build --wait
   docker compose ps
   ```

3. Open **http://localhost:8000**. The default configuration runs the trusted local/LAN demo; its Organizer code is stored privately in `.env`.

Useful commands:

```bash
docker compose logs -f arena controller
docker compose down                    # Keeps named data volumes
```

> Do not use `docker compose down -v` if you want to retain data. Do not commit `.env`.

## Repository structure

```text
backend/             API, accounts, matchmaking, and game engines
frontend/            Web application and match visualization
sandbox_controller/  Isolated bot execution controller
samples/             Example bots
tests/               Automated tests
docs/                Specifications, QA, and operator guides
deploy/              Gateway and deployment configuration
```

## Documentation

- [Docker sandbox and local setup](docs/SANDBOX.md)
- [Game adapters and bot protocol](docs/ADAPTERS.md)
- [Team tournament rules and API](docs/TEAM_TOURNAMENTS.md)
- [Account registration and recovery](docs/USERNAME_ONLY_SIGNUP.md)
- [Deployment and organizer handover](docs/PHASE_4_3_OPERATOR_HANDOVER.md)
- [Release QA and acceptance](docs/PHASE_4_3_CONSOLIDATED_QA.md)

## Deployment and security

The default Compose setup is intended for **trusted local/LAN use**, not direct Internet exposure. Account-Only authentication, registration, and the HTTPS gateway require explicit configuration and acceptance testing; public signup is disabled by default. The sandbox controller has privileged Docker Engine access and must never be publicly exposed.

Before upgrading an existing installation, back up the data volumes and rehearse any SQLite migrations offline. Follow the deployment and QA guides above before enabling public access.

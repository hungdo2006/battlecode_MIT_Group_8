"""Versioned account schema. Never edit a released migration; add another one."""

# No game/season tables here: game_id and bot_id refer to the existing registry
# and JSON metadata. Cross-store validation belongs to a future domain service.
FOUNDATION = (
    """CREATE TABLE users (
        id TEXT PRIMARY KEY NOT NULL,
        username TEXT NOT NULL UNIQUE CHECK (
            length(username) BETWEEN 3 AND 32 AND username = lower(trim(username))
            AND username NOT GLOB '*[^a-z0-9_.-]*'),
        display_name TEXT NOT NULL CHECK (length(trim(display_name)) BETWEEN 1 AND 64),
        system_role TEXT NOT NULL CHECK (system_role IN ('ADMIN', 'PLAYER')),
        status TEXT NOT NULL CHECK (status IN ('INVITED', 'ACTIVE', 'DISABLED')),
        password_hash TEXT CHECK (password_hash IS NULL OR password_hash LIKE '$argon2id$%'),
        auth_version INTEGER NOT NULL DEFAULT 1 CHECK (auth_version >= 1),
        created_at INTEGER NOT NULL CHECK (created_at >= 0),
        updated_at INTEGER NOT NULL CHECK (updated_at >= created_at),
        password_changed_at INTEGER CHECK (password_changed_at >= created_at),
        CHECK (status != 'ACTIVE' OR password_hash IS NOT NULL)
    ) STRICT""",
    """CREATE TABLE auth_sessions (
        id TEXT PRIMARY KEY NOT NULL,
        token_hash TEXT NOT NULL UNIQUE CHECK (
            length(token_hash) = 64 AND token_hash NOT GLOB '*[^0-9a-f]*'),
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        audience TEXT NOT NULL CHECK (audience IN ('PLAYER', 'ADMIN')),
        auth_version INTEGER NOT NULL CHECK (auth_version >= 1),
        created_at INTEGER NOT NULL CHECK (created_at >= 0),
        expires_at INTEGER NOT NULL CHECK (expires_at > created_at),
        last_seen_at INTEGER CHECK (last_seen_at >= created_at),
        revoked_at INTEGER CHECK (revoked_at >= created_at)
    ) STRICT""",
    "CREATE INDEX auth_sessions_user ON auth_sessions(user_id, expires_at)",
    """CREATE TABLE account_tokens (
        id TEXT PRIMARY KEY NOT NULL,
        token_hash TEXT NOT NULL UNIQUE CHECK (
            length(token_hash) = 64 AND token_hash NOT GLOB '*[^0-9a-f]*'),
        purpose TEXT NOT NULL CHECK (purpose IN ('ACCOUNT_INVITE', 'PASSWORD_RESET', 'LEGACY_CLAIM')),
        user_id TEXT REFERENCES users(id) ON DELETE RESTRICT,
        created_by TEXT REFERENCES users(id) ON DELETE RESTRICT,
        created_at INTEGER NOT NULL CHECK (created_at >= 0),
        expires_at INTEGER NOT NULL CHECK (expires_at > created_at),
        consumed_at INTEGER CHECK (consumed_at >= created_at),
        revoked_at INTEGER CHECK (revoked_at >= created_at),
        CHECK (purpose = 'ACCOUNT_INVITE' OR user_id IS NOT NULL)
    ) STRICT""",
    """CREATE TABLE teams (
        id TEXT PRIMARY KEY NOT NULL,
        slug TEXT NOT NULL UNIQUE CHECK (
            length(slug) BETWEEN 3 AND 48 AND slug = lower(trim(slug))
            AND slug NOT GLOB '*[^a-z0-9-]*'),
        display_name TEXT NOT NULL CHECK (length(trim(display_name)) BETWEEN 1 AND 64),
        status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'ACTIVE', 'ARCHIVED')),
        created_by TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        created_at INTEGER NOT NULL CHECK (created_at >= 0),
        updated_at INTEGER NOT NULL CHECK (updated_at >= created_at)
    ) STRICT""",
    """CREATE TABLE team_memberships (
        id TEXT PRIMARY KEY NOT NULL,
        team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        team_role TEXT NOT NULL CHECK (team_role IN ('CAPTAIN', 'MEMBER')),
        joined_at INTEGER NOT NULL CHECK (joined_at >= 0),
        left_at INTEGER CHECK (left_at >= joined_at)
    ) STRICT""",
    """CREATE UNIQUE INDEX membership_active_pair
        ON team_memberships(team_id, user_id) WHERE left_at IS NULL""",
    """CREATE UNIQUE INDEX membership_active_captain
        ON team_memberships(team_id) WHERE left_at IS NULL AND team_role = 'CAPTAIN'""",
    """CREATE TRIGGER membership_player_insert BEFORE INSERT ON team_memberships
        WHEN NEW.left_at IS NULL AND
             (SELECT system_role FROM users WHERE id = NEW.user_id) != 'PLAYER'
        BEGIN SELECT RAISE(ABORT, 'Only PLAYER accounts may join teams'); END""",
    """CREATE TRIGGER membership_player_update BEFORE UPDATE ON team_memberships
        WHEN NEW.left_at IS NULL AND
             (SELECT system_role FROM users WHERE id = NEW.user_id) != 'PLAYER'
        BEGIN SELECT RAISE(ABORT, 'Only PLAYER accounts may join teams'); END""",
    """CREATE TRIGGER user_role_membership BEFORE UPDATE OF system_role ON users
        WHEN NEW.system_role = 'ADMIN' AND EXISTS (
            SELECT 1 FROM team_memberships WHERE user_id = NEW.id AND left_at IS NULL)
        BEGIN SELECT RAISE(ABORT, 'End team memberships before changing system role'); END""",
    """CREATE TABLE team_invitations (
        id TEXT PRIMARY KEY NOT NULL,
        team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
        invited_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        invited_by TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
            status IN ('PENDING', 'ACCEPTED', 'DECLINED', 'REVOKED', 'EXPIRED')),
        created_at INTEGER NOT NULL CHECK (created_at >= 0),
        expires_at INTEGER NOT NULL CHECK (expires_at > created_at),
        responded_at INTEGER CHECK (responded_at >= created_at),
        CHECK ((status = 'PENDING' AND responded_at IS NULL)
            OR (status != 'PENDING' AND responded_at IS NOT NULL))
    ) STRICT""",
    """CREATE UNIQUE INDEX invitation_pending_pair
        ON team_invitations(team_id, invited_user_id) WHERE status = 'PENDING'""",
    """CREATE TABLE submission_ownership (
        bot_id TEXT PRIMARY KEY NOT NULL CHECK (length(bot_id) BETWEEN 1 AND 128),
        team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
        game_id TEXT NOT NULL CHECK (length(game_id) BETWEEN 1 AND 64),
        uploaded_by TEXT REFERENCES users(id) ON DELETE RESTRICT,
        origin TEXT NOT NULL CHECK (origin IN ('NEW', 'LEGACY_VERIFIED')),
        created_at INTEGER NOT NULL CHECK (created_at >= 0),
        UNIQUE (team_id, game_id, bot_id),
        CHECK (origin != 'NEW' OR uploaded_by IS NOT NULL)
    ) STRICT""",
    """CREATE TABLE team_game_bots (
        team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
        game_id TEXT NOT NULL,
        bot_id TEXT NOT NULL,
        selected_by TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        selected_at INTEGER NOT NULL CHECK (selected_at >= 0),
        revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
        PRIMARY KEY (team_id, game_id),
        FOREIGN KEY (team_id, game_id, bot_id)
            REFERENCES submission_ownership(team_id, game_id, bot_id) ON DELETE RESTRICT
    ) STRICT""",
    """CREATE TABLE audit_events (
        id INTEGER PRIMARY KEY,
        occurred_at INTEGER NOT NULL CHECK (occurred_at >= 0),
        actor_user_id TEXT REFERENCES users(id) ON DELETE RESTRICT,
        action TEXT NOT NULL CHECK (length(action) BETWEEN 1 AND 80),
        target_type TEXT NOT NULL CHECK (length(target_type) BETWEEN 1 AND 40),
        target_id TEXT NOT NULL CHECK (length(target_id) BETWEEN 1 AND 128),
        details_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(details_json))
    ) STRICT""",
    "CREATE INDEX audit_events_time ON audit_events(occurred_at, id)",
)

# Append-only v2: pin idle policy per session. No B.1 issuer existed; any
# pre-service/manual sessions lack an accepted idle policy and must be revoked.
AUTH_SERVICE_CORE = (
    """ALTER TABLE auth_sessions ADD COLUMN idle_timeout_seconds INTEGER NOT NULL
        DEFAULT 1 CHECK (idle_timeout_seconds > 0)""",
    """UPDATE auth_sessions SET
        revoked_at = COALESCE(revoked_at, max(created_at, CAST(strftime('%s', 'now') AS INTEGER))),
        last_seen_at = COALESCE(last_seen_at, created_at)""",
)

MIGRATIONS = (
    (1, "account_foundation", FOUNDATION),
    (2, "auth_service_core", AUTH_SERVICE_CORE),
    (3, "team_lifecycle_membership", (
        """CREATE UNIQUE INDEX membership_active_user_global
            ON team_memberships(user_id) WHERE left_at IS NULL""",
        "CREATE INDEX team_memberships_team_active ON team_memberships(team_id, left_at)",
        "CREATE INDEX team_invitations_user_status ON team_invitations(invited_user_id, status)",
    )),
)

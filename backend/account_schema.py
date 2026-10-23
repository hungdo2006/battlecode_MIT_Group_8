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
    (4, "team_submission_journal", (
        """CREATE TABLE submission_journal (
            bot_id TEXT PRIMARY KEY NOT NULL,
            team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            game_id TEXT NOT NULL,
            uploaded_by TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at INTEGER NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('PREPARING','RECOVERING','COMMITTED','ABORTED'))
        ) STRICT""",
        "CREATE INDEX submission_journal_team ON submission_journal(team_id, state)",
    )),
    (5, "official_match_scheduling", (
        """CREATE TABLE official_match_requests (
            id TEXT PRIMARY KEY NOT NULL,
            created_by TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            team_a_id TEXT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            team_b_id TEXT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            game_id TEXT NOT NULL CHECK (length(game_id) BETWEEN 1 AND 64),
            rules_json TEXT NOT NULL CHECK (json_valid(rules_json)),
            bot_lock_at INTEGER NOT NULL CHECK (bot_lock_at >= 0),
            scheduled_at INTEGER NOT NULL CHECK (scheduled_at >= bot_lock_at),
            created_at INTEGER NOT NULL CHECK (created_at >= 0),
            status TEXT NOT NULL CHECK (status IN
                ('SCHEDULED','LOCKED','BLOCKED','CANCELLED',
                 'DISPATCHING','RUNNING','COMPLETED','INTERRUPTED')),
            locked_at INTEGER CHECK (locked_at >= created_at),
            status_reason TEXT,
            match_id TEXT UNIQUE,
            started_at INTEGER,
            finished_at INTEGER,
            outcome_json TEXT CHECK (outcome_json IS NULL OR json_valid(outcome_json)),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            CHECK (team_a_id <> team_b_id),
            CHECK (bot_lock_at >= created_at),
            CHECK ((status IN ('LOCKED','DISPATCHING','RUNNING','COMPLETED','INTERRUPTED')
                AND locked_at IS NOT NULL)
                OR (status IN ('SCHEDULED','BLOCKED','CANCELLED')
                AND locked_at IS NULL)),
            CHECK ((status IN ('DISPATCHING','RUNNING','COMPLETED','INTERRUPTED')
                AND match_id IS NOT NULL AND started_at IS NOT NULL)
                OR (status IN ('SCHEDULED','LOCKED','BLOCKED','CANCELLED')
                AND match_id IS NULL AND started_at IS NULL)),
            CHECK (finished_at IS NULL OR finished_at >= started_at)
        ) STRICT""",
        "CREATE INDEX official_due ON official_match_requests(status, bot_lock_at)",
        "CREATE INDEX official_schedule ON official_match_requests(scheduled_at, id)",
        """CREATE TABLE official_source_attestations (
            bot_id TEXT PRIMARY KEY NOT NULL REFERENCES submission_ownership(bot_id)
                ON DELETE RESTRICT,
            source_sha256 TEXT NOT NULL CHECK (
                length(source_sha256)=64 AND
                source_sha256 NOT GLOB '*[^0-9a-f]*'),
            attested_at INTEGER NOT NULL CHECK (attested_at >= 0)
        ) STRICT""",
        """CREATE TABLE official_match_slots (
            request_id TEXT NOT NULL REFERENCES official_match_requests(id) ON DELETE RESTRICT,
            side TEXT NOT NULL CHECK (side IN ('A','B')),
            team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            team_name_snapshot TEXT NOT NULL,
            game_id TEXT NOT NULL,
            bot_id TEXT NOT NULL,
            bot_name_snapshot TEXT NOT NULL,
            bot_language TEXT NOT NULL,
            source_sha256 TEXT NOT NULL CHECK (length(source_sha256)=64),
            artifact_id TEXT,
            artifact_digest TEXT,
            bot_revision INTEGER NOT NULL CHECK (bot_revision > 0),
            locked_at INTEGER NOT NULL CHECK (locked_at >= 0),
            PRIMARY KEY (request_id,side),
            FOREIGN KEY (team_id,game_id,bot_id)
                REFERENCES submission_ownership(team_id,game_id,bot_id) ON DELETE RESTRICT
        ) STRICT""",
    )),
    # Append-only v6. Self-registration email addresses are UNVERIFIED until a
    # future delivery/verification provider is configured; never authorize
    # password recovery or account elevation based on these addresses.
    (6, "player_registration_email", (
        """CREATE TABLE user_emails (
            user_id TEXT PRIMARY KEY NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            email TEXT NOT NULL UNIQUE CHECK (length(email) BETWEEN 3 AND 254),
            verified_at INTEGER CHECK (verified_at >= 0)
        ) STRICT""",
    )),
    (7, "admin_totp_mfa", (
        """CREATE TABLE admin_totp (
            user_id TEXT PRIMARY KEY NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            secret TEXT NOT NULL CHECK (length(secret) = 32 AND secret NOT GLOB '*[^A-Z2-7]*'),
            last_counter INTEGER NOT NULL DEFAULT -1 CHECK (last_counter >= -1),
            enrolled_at INTEGER NOT NULL CHECK (enrolled_at >= 0)
        ) STRICT""",
    )),
    (8, "player_email_verification", (
        """CREATE TABLE email_verification_tokens (
            id TEXT PRIMARY KEY NOT NULL,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            token_hash TEXT NOT NULL UNIQUE CHECK (
                length(token_hash)=64 AND token_hash NOT GLOB '*[^0-9a-f]*'),
            created_at INTEGER NOT NULL CHECK(created_at>=0),
            expires_at INTEGER NOT NULL CHECK(expires_at>created_at),
            consumed_at INTEGER CHECK(consumed_at IS NULL OR consumed_at>=created_at)
        ) STRICT""",
        "CREATE INDEX email_verification_user ON email_verification_tokens(user_id,consumed_at)",
    )),
    (9, "admin_mfa_session_proof", (
        """ALTER TABLE auth_sessions ADD COLUMN mfa_verified INTEGER NOT NULL
            DEFAULT 0 CHECK (mfa_verified IN (0,1))""",
    )),
    (10, "team_tournaments", (
        """CREATE TABLE team_tournaments (
            id TEXT PRIMARY KEY NOT NULL,
            name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 64),
            game_id TEXT NOT NULL CHECK (length(game_id) BETWEEN 1 AND 64),
            format TEXT NOT NULL CHECK (format = 'round_robin'),
            status TEXT NOT NULL CHECK (status IN ('REGISTRATION','ACTIVE','COMPLETED','CANCELLED')),
            created_by TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at INTEGER NOT NULL CHECK (created_at >= 0),
            started_at INTEGER CHECK (started_at IS NULL OR started_at >= created_at)
        ) STRICT""",
        "CREATE INDEX team_tournaments_status ON team_tournaments(status, created_at DESC)",
        """CREATE TABLE team_tournament_entries (
            tournament_id TEXT NOT NULL REFERENCES team_tournaments(id) ON DELETE RESTRICT,
            team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            team_name_snapshot TEXT NOT NULL CHECK (length(trim(team_name_snapshot)) BETWEEN 1 AND 64),
            PRIMARY KEY (tournament_id, team_id)
        ) STRICT""",
        """CREATE TABLE team_tournament_fixtures (
            id TEXT PRIMARY KEY NOT NULL,
            tournament_id TEXT NOT NULL REFERENCES team_tournaments(id) ON DELETE RESTRICT,
            round_number INTEGER NOT NULL CHECK (round_number > 0),
            team_a_id TEXT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            team_b_id TEXT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            official_request_id TEXT UNIQUE REFERENCES official_match_requests(id) ON DELETE RESTRICT,
            created_at INTEGER NOT NULL CHECK (created_at >= 0),
            CHECK (team_a_id <> team_b_id),
            UNIQUE (tournament_id, round_number, team_a_id, team_b_id)
        ) STRICT""",
        "CREATE INDEX team_tournament_fixtures_tournament ON team_tournament_fixtures(tournament_id, round_number, id)",
        """CREATE TABLE team_tournament_audit (
            id INTEGER PRIMARY KEY,
            tournament_id TEXT NOT NULL REFERENCES team_tournaments(id) ON DELETE RESTRICT,
            fixture_id TEXT REFERENCES team_tournament_fixtures(id) ON DELETE RESTRICT,
            actor_user_id TEXT REFERENCES users(id) ON DELETE RESTRICT,
            action TEXT NOT NULL CHECK (length(action) BETWEEN 1 AND 64),
            occurred_at INTEGER NOT NULL CHECK (occurred_at >= 0)
        ) STRICT""",
    )),
    (11, "team_tournament_brackets_and_attempts", (
        """CREATE TABLE team_tournament_format_overrides (
            tournament_id TEXT PRIMARY KEY NOT NULL REFERENCES team_tournaments(id) ON DELETE RESTRICT,
            format TEXT NOT NULL CHECK (format IN ('single_elimination'))
        ) STRICT""",
        """CREATE TABLE team_tournament_bracket_slots (
            id TEXT PRIMARY KEY NOT NULL,
            tournament_id TEXT NOT NULL REFERENCES team_tournaments(id) ON DELETE RESTRICT,
            round_number INTEGER NOT NULL CHECK (round_number > 0),
            match_number INTEGER NOT NULL CHECK (match_number > 0),
            team_a_id TEXT REFERENCES teams(id) ON DELETE RESTRICT,
            team_b_id TEXT REFERENCES teams(id) ON DELETE RESTRICT,
            source_a_slot_id TEXT REFERENCES team_tournament_bracket_slots(id) ON DELETE RESTRICT,
            source_b_slot_id TEXT REFERENCES team_tournament_bracket_slots(id) ON DELETE RESTRICT,
            fixture_id TEXT UNIQUE REFERENCES team_tournament_fixtures(id) ON DELETE RESTRICT,
            winner_team_id TEXT REFERENCES teams(id) ON DELETE RESTRICT,
            status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','READY','COMPLETED','BYE','TIE')),
            UNIQUE (tournament_id,round_number,match_number),
            CHECK (team_a_id IS NULL OR team_b_id IS NULL OR team_a_id <> team_b_id)
        ) STRICT""",
        "CREATE INDEX team_tournament_bracket_order ON team_tournament_bracket_slots(tournament_id,round_number,match_number)",
        """CREATE TABLE team_tournament_fixture_matches (
            fixture_id TEXT NOT NULL REFERENCES team_tournament_fixtures(id) ON DELETE RESTRICT,
            official_request_id TEXT NOT NULL UNIQUE REFERENCES official_match_requests(id) ON DELETE RESTRICT,
            attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
            created_at INTEGER NOT NULL CHECK (created_at >= 0),
            PRIMARY KEY (fixture_id,attempt_number)
        ) STRICT""",
    )),
    (12, "team_tournament_group_stage", (
        "ALTER TABLE team_tournament_format_overrides RENAME TO team_tournament_format_overrides_v11",
        """CREATE TABLE team_tournament_format_overrides (
            tournament_id TEXT PRIMARY KEY NOT NULL REFERENCES team_tournaments(id) ON DELETE RESTRICT,
            format TEXT NOT NULL CHECK (format IN ('single_elimination','group_knockout'))
        ) STRICT""",
        """INSERT INTO team_tournament_format_overrides(tournament_id,format)
            SELECT tournament_id,format FROM team_tournament_format_overrides_v11""",
        "DROP TABLE team_tournament_format_overrides_v11",
        """CREATE TABLE team_tournament_groups (
            id TEXT PRIMARY KEY NOT NULL,
            tournament_id TEXT NOT NULL REFERENCES team_tournaments(id) ON DELETE RESTRICT,
            group_number INTEGER NOT NULL CHECK (group_number > 0),
            name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 16),
            UNIQUE (tournament_id,group_number), UNIQUE (tournament_id,id)
        ) STRICT""",
        """CREATE TABLE team_tournament_group_entries (
            tournament_id TEXT NOT NULL,
            group_id TEXT NOT NULL,
            team_id TEXT NOT NULL,
            PRIMARY KEY (tournament_id,team_id),
            UNIQUE (group_id,team_id),
            FOREIGN KEY (tournament_id,group_id) REFERENCES team_tournament_groups(tournament_id,id) ON DELETE RESTRICT,
            FOREIGN KEY (tournament_id,team_id) REFERENCES team_tournament_entries(tournament_id,team_id) ON DELETE RESTRICT
        ) STRICT""",
        "ALTER TABLE team_tournament_fixtures ADD COLUMN stage TEXT NOT NULL DEFAULT 'KNOCKOUT' CHECK (stage IN ('GROUP','KNOCKOUT'))",
        "ALTER TABLE team_tournament_fixtures ADD COLUMN group_id TEXT REFERENCES team_tournament_groups(id) ON DELETE RESTRICT",
        "ALTER TABLE team_tournament_bracket_slots ADD COLUMN source_a_group_id TEXT REFERENCES team_tournament_groups(id) ON DELETE RESTRICT",
        "ALTER TABLE team_tournament_bracket_slots ADD COLUMN source_a_group_rank INTEGER CHECK (source_a_group_rank IS NULL OR source_a_group_rank > 0)",
        "ALTER TABLE team_tournament_bracket_slots ADD COLUMN source_b_group_id TEXT REFERENCES team_tournament_groups(id) ON DELETE RESTRICT",
        "ALTER TABLE team_tournament_bracket_slots ADD COLUMN source_b_group_rank INTEGER CHECK (source_b_group_rank IS NULL OR source_b_group_rank > 0)",
    )),
    (13, "team_tournament_double_elimination", (
        "ALTER TABLE team_tournament_format_overrides RENAME TO team_tournament_format_overrides_v12",
        """CREATE TABLE team_tournament_format_overrides (
            tournament_id TEXT PRIMARY KEY NOT NULL REFERENCES team_tournaments(id) ON DELETE RESTRICT,
            format TEXT NOT NULL CHECK (format IN ('single_elimination','group_knockout','double_elimination'))
        ) STRICT""",
        """INSERT INTO team_tournament_format_overrides(tournament_id,format)
            SELECT tournament_id,format FROM team_tournament_format_overrides_v12""",
        "DROP TABLE team_tournament_format_overrides_v12",
        "ALTER TABLE team_tournament_bracket_slots ADD COLUMN bracket TEXT NOT NULL DEFAULT 'MAIN' CHECK (bracket IN ('MAIN','WINNERS','LOSERS','FINAL','RESET'))",
        "ALTER TABLE team_tournament_bracket_slots ADD COLUMN source_a_result TEXT NOT NULL DEFAULT 'WINNER' CHECK (source_a_result IN ('WINNER','LOSER'))",
        "ALTER TABLE team_tournament_bracket_slots ADD COLUMN source_b_result TEXT NOT NULL DEFAULT 'WINNER' CHECK (source_b_result IN ('WINNER','LOSER'))",
        "ALTER TABLE team_tournament_bracket_slots ADD COLUMN conditional_status TEXT NOT NULL DEFAULT '' CHECK (conditional_status IN ('','WAITING','ACTIVE','SKIPPED'))",
    )),
    (14, "team_tournament_swiss_stage", (
        "ALTER TABLE team_tournament_format_overrides RENAME TO team_tournament_format_overrides_v13",
        """CREATE TABLE team_tournament_format_overrides (
            tournament_id TEXT PRIMARY KEY NOT NULL REFERENCES team_tournaments(id) ON DELETE RESTRICT,
            format TEXT NOT NULL CHECK (format IN ('single_elimination','group_knockout','double_elimination','swiss_single_elimination'))
        ) STRICT""",
        """INSERT INTO team_tournament_format_overrides(tournament_id,format)
            SELECT tournament_id,format FROM team_tournament_format_overrides_v13""",
        "DROP TABLE team_tournament_format_overrides_v13",
        """CREATE TABLE team_tournament_swiss_byes (
            tournament_id TEXT NOT NULL REFERENCES team_tournaments(id) ON DELETE RESTRICT,
            round_number INTEGER NOT NULL CHECK (round_number > 0),
            team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            PRIMARY KEY (tournament_id,round_number),
            UNIQUE (tournament_id,round_number,team_id),
            FOREIGN KEY (tournament_id,team_id) REFERENCES team_tournament_entries(tournament_id,team_id) ON DELETE RESTRICT
        ) STRICT""",
    )),
    (15, "team_tournament_large_fields", (
        "ALTER TABLE team_tournaments ADD COLUMN qualifier_target INTEGER CHECK (qualifier_target IS NULL OR qualifier_target IN (16,64))",
    )),
    (16, "asynchronous_team_scrimmages", (
        """CREATE TABLE scrimmage_requests (
            id TEXT PRIMARY KEY NOT NULL,
            requested_by TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            team_a_id TEXT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            team_b_id TEXT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            game_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('QUEUED','DISPATCHING','RUNNING','COMPLETED','INTERRUPTED','CANCELLED')),
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            match_id TEXT UNIQUE,
            plan_json TEXT NOT NULL CHECK (json_valid(plan_json)),
            outcome_json TEXT CHECK (outcome_json IS NULL OR json_valid(outcome_json)),
            status_reason TEXT,
            CHECK (team_a_id != team_b_id)
        ) STRICT""",
        "CREATE INDEX scrimmage_queue ON scrimmage_requests(status,created_at,id)",
        "CREATE INDEX scrimmage_team_a ON scrimmage_requests(team_a_id,created_at)",
        "CREATE INDEX scrimmage_team_b ON scrimmage_requests(team_b_id,created_at)",
    )),
    (17, "competition_season_registration", (
        """CREATE TABLE competition_seasons (
            id TEXT PRIMARY KEY NOT NULL,
            name TEXT NOT NULL,
            game_id TEXT NOT NULL,
            registration_opens_at INTEGER NOT NULL,
            registration_closes_at INTEGER NOT NULL,
            starts_at INTEGER NOT NULL,
            ends_at INTEGER NOT NULL,
            max_teams INTEGER NOT NULL CHECK (max_teams BETWEEN 2 AND 256),
            created_by TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at INTEGER NOT NULL,
            registration_closed_at INTEGER,
            tournament_id TEXT UNIQUE REFERENCES team_tournaments(id) ON DELETE RESTRICT,
            published_at INTEGER,
            publication_json TEXT CHECK (publication_json IS NULL OR json_valid(publication_json)),
            CHECK (registration_opens_at < registration_closes_at AND registration_closes_at <= starts_at AND starts_at < ends_at)
        ) STRICT""",
        """CREATE TABLE competition_season_entries (
            season_id TEXT NOT NULL REFERENCES competition_seasons(id) ON DELETE RESTRICT,
            team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            registered_by TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            registered_at INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('REGISTERED','WITHDRAWN')),
            PRIMARY KEY (season_id,team_id)
        ) STRICT""",
    )),
    (18, "team_capacity_and_submission_archive", (
        """CREATE TABLE team_policy (
            id INTEGER PRIMARY KEY CHECK (id=1),
            max_members INTEGER NOT NULL CHECK (max_members BETWEEN 2 AND 20),
            updated_at INTEGER NOT NULL CHECK (updated_at>=0),
            updated_by TEXT REFERENCES users(id) ON DELETE RESTRICT
        ) STRICT""",
        "INSERT INTO team_policy(id,max_members,updated_at) VALUES (1,5,0)",
        """CREATE TABLE submission_archives (
            bot_id TEXT PRIMARY KEY REFERENCES submission_ownership(bot_id) ON DELETE RESTRICT,
            archived_by TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            archived_at INTEGER NOT NULL CHECK (archived_at>=0)
        ) STRICT""",
    )),
    (19, "opt_in_practice_matchmaking", (
        """CREATE TABLE matchmaking_searches (
            id TEXT PRIMARY KEY NOT NULL,
            team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE RESTRICT,
            requested_by TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            game_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('SEARCHING','MATCHED','CANCELLED','EXPIRED','ERROR')),
            created_at INTEGER NOT NULL CHECK (created_at>=0),
            expires_at INTEGER NOT NULL CHECK (expires_at>created_at),
            updated_at INTEGER NOT NULL CHECK (updated_at>=created_at),
            request_id TEXT REFERENCES scrimmage_requests(id) ON DELETE RESTRICT,
            status_reason TEXT,
            CHECK ((status='MATCHED' AND request_id IS NOT NULL) OR (status!='MATCHED' AND request_id IS NULL))
        ) STRICT""",
        "CREATE UNIQUE INDEX matchmaking_one_search ON matchmaking_searches(team_id) WHERE status='SEARCHING'",
        "CREATE INDEX matchmaking_waiting ON matchmaking_searches(status,game_id,created_at,id)",
        "CREATE INDEX matchmaking_team_history ON matchmaking_searches(team_id,created_at DESC,id DESC)",
    )),
    (20, "tournament_round_rules_and_visibility", (
        """CREATE TABLE team_tournament_round_rules (
            tournament_id TEXT NOT NULL REFERENCES team_tournaments(id) ON DELETE RESTRICT,
            stage TEXT NOT NULL CHECK (stage IN ('GROUP','KNOCKOUT')),
            round_number INTEGER NOT NULL CHECK (round_number > 0),
            rules_json TEXT NOT NULL CHECK (json_valid(rules_json)),
            status TEXT NOT NULL CHECK (status IN ('DRAFT','PUBLISHED')),
            editing_minutes INTEGER NOT NULL CHECK (editing_minutes IN (15,20)),
            published_at INTEGER CHECK (published_at IS NULL OR published_at >= 0),
            updated_by TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            updated_at INTEGER NOT NULL CHECK (updated_at >= 0),
            PRIMARY KEY (tournament_id,stage,round_number),
            CHECK ((status='DRAFT' AND published_at IS NULL)
                OR (status='PUBLISHED' AND published_at IS NOT NULL))
        ) STRICT""",
        "ALTER TABLE team_tournaments ADD COLUMN visibility TEXT NOT NULL DEFAULT 'PRIVATE' CHECK (visibility IN ('PRIVATE','SIGNED_IN','PUBLIC'))",
    )),
)

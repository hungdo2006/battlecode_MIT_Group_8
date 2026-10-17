"""Unit tests for Phase 4.2C1 TeamService domain logic.

Tests Team lifecycle, global single membership, Captain succession,
invitations, RBAC, IDOR protection, admin recovery, and audit logs.
"""
import sqlite3
from types import SimpleNamespace
import pytest

from backend.account_database import AccountDatabase, check_integrity
from backend.admin_cli import bootstrap_admin
from backend.auth_service import AuthService, PermissionDenied
from backend.team_service import (
    InvalidInvitation, TeamConflict, TeamNotFound, TeamPermissionDenied, TeamService, TeamValidationError
)
from backend.writer_lock import WriterLock


PASSWORD = "test-only player account passphrase 73"


class Clock:
    def __init__(self):
        self.now = 2_000_000_000

    def __call__(self):
        return self.now


class TestLimiter:
    __test__ = False

    def check(self, attempt):
        pass

    def record(self, attempt, *, succeeded):
        pass


@pytest.fixture
def env(tmp_path):
    data = tmp_path / "data"
    admin_id = bootstrap_admin(data, "admin", PASSWORD)
    clock, limiter = Clock(), TestLimiter()
    database = AccountDatabase(data)
    with WriterLock(data) as writer:
        with database.writer_connection(writer) as connection:
            auth = AuthService(connection, writer, clock=clock, login_limiter=limiter)
            admin = auth.login("admin", PASSWORD, audience="ADMIN", source_key="test-peer").principal
            team = TeamService(connection, writer, auth_service=auth, clock=clock)
            yield SimpleNamespace(
                auth=auth, team=team, connection=connection, writer=writer,
                clock=clock, database=database, admin=admin, admin_id=admin_id
            )


def make_player(env, username):
    invitation = env.auth.issue_invitation(env.admin, username)
    env.auth.activate(invitation.token, PASSWORD)
    return env.auth.login(username, PASSWORD, audience="PLAYER", source_key="test-peer").principal


def test_create_team_atomic_captain_and_audit(env):
    alice = make_player(env, "alice")
    created = env.team.create_team(alice, "neon-knights", "Neon Knights")
    assert created.slug == "neon-knights"
    assert created.display_name == "Neon Knights"
    assert created.status == "DRAFT"
    assert created.created_by == alice.account.id
    assert created.captain_id == alice.account.id
    assert created.member_count == 1

    # Verify membership table
    members = env.team.list_members(alice, created.id)
    assert len(members) == 1
    assert members[0].user_id == alice.account.id
    assert members[0].team_role == "CAPTAIN"
    assert members[0].joined_at == env.clock.now
    assert members[0].left_at is None

    # Verify audit event
    audit = env.connection.execute(
        "SELECT * FROM audit_events WHERE target_id = ? AND action = 'TEAM_CREATED'",
        (created.id,)).fetchone()
    assert audit is not None
    assert audit["actor_user_id"] == alice.account.id


def test_slug_validation_and_uniqueness(env):
    alice = make_player(env, "alice")
    bob = make_player(env, "bob")
    # Valid with uppercase/whitespace normalization
    t = env.team.create_team(alice, "  CYBER-WARRIORS  ", "Cyber Warriors")
    assert t.slug == "cyber-warriors"

    # Duplicate slug rejected
    with pytest.raises(TeamConflict, match="slug is already in use"):
        env.team.create_team(bob, "cyber-warriors", "Another Team")

    # Invalid slug formats
    for bad_slug in ["ab", "a" * 49, "slug with spaces", "slug_underscores", "slug@bad"]:
        with pytest.raises(TeamValidationError):
            env.team.create_team(bob, bad_slug, "Valid Name")


def test_global_single_active_team_constraint(env):
    alice = make_player(env, "alice")
    bob = make_player(env, "bob")
    t1 = env.team.create_team(alice, "team-one", "Team One")

    # Alice cannot create a second team while active in team-one
    with pytest.raises(TeamConflict, match="already has an active team"):
        env.team.create_team(alice, "team-two", "Team Two")

    # Bob creates team-two and invites Alice
    t2 = env.team.create_team(bob, "team-two", "Team Two")
    invitation = env.team.invite_member(bob, t2.id, username="alice")

    # Alice cannot accept invitation while active in team-one
    with pytest.raises(TeamConflict, match="already has an active team membership"):
        env.team.accept_invitation(alice, invitation.id)


def test_admin_cannot_create_or_join_team(env):
    with pytest.raises(PermissionDenied):
        env.team.create_team(env.admin, "admin-team", "Admin Team")


def test_get_my_team_and_get_team_rbac(env):
    alice = make_player(env, "alice")
    bob = make_player(env, "bob")
    assert env.team.get_my_team(alice) is None

    t1 = env.team.create_team(alice, "team-alpha", "Team Alpha")
    my_team = env.team.get_my_team(alice)
    assert my_team is not None
    assert my_team.team.id == t1.id
    assert my_team.my_role == "CAPTAIN"

    # Alice can inspect team-alpha
    assert env.team.get_team(alice, t1.id).slug == "team-alpha"

    # Bob (non-member) cannot inspect team-alpha (IDOR protection)
    with pytest.raises(TeamPermissionDenied):
        env.team.get_team(bob, t1.id)

    # Admin can inspect team-alpha
    assert env.team.get_team(env.admin, t1.id).slug == "team-alpha"

    # Unknown team raises TeamNotFound
    with pytest.raises(TeamNotFound):
        env.team.get_team(env.admin, "missing-team-id")


def test_update_team_lifecycle(env):
    alice = make_player(env, "alice")
    bob = make_player(env, "bob")
    t = env.team.create_team(alice, "team-alpha", "Initial Name")

    # Member / non-member cannot update
    with pytest.raises(TeamPermissionDenied):
        env.team.update_team(bob, t.id, display_name="Bob Hacked Name")

    # Captain can update display name
    updated = env.team.update_team(alice, t.id, display_name="Renamed Alpha")
    assert updated.display_name == "Renamed Alpha"
    assert updated.slug == "team-alpha"  # slug is immutable

    audit = env.connection.execute(
        "SELECT * FROM audit_events WHERE target_id = ? AND action = 'TEAM_UPDATED'",
        (t.id,)).fetchone()
    assert audit is not None


def test_activate_team(env):
    alice = make_player(env, "alice")
    bob = make_player(env, "bob")
    t = env.team.create_team(alice, "team-draft", "Team Draft")
    assert t.status == "DRAFT"

    # Non-captain cannot activate
    with pytest.raises(TeamPermissionDenied):
        env.team.activate_team(bob, t.id)

    # Captain activates team
    activated = env.team.activate_team(alice, t.id)
    assert activated.status == "ACTIVE"

    # Activating already active team raises conflict
    with pytest.raises(TeamConflict, match="already active"):
        env.team.activate_team(alice, t.id)


def test_invitation_lifecycle_and_expiry(env):
    alice = make_player(env, "alice")
    bob = make_player(env, "bob")
    t = env.team.create_team(alice, "knights", "Knights")

    # Captain invites Bob
    inv = env.team.invite_member(alice, t.id, username="bob", ttl_seconds=100)
    assert inv.status == "PENDING"
    assert inv.invited_user_id == bob.account.id
    assert inv.expires_at == env.clock.now + 100

    # Duplicate pending invitation rejected
    with pytest.raises(TeamConflict, match="pending invitation already exists"):
        env.team.invite_member(alice, t.id, username="bob")

    # Advance clock past expiration
    env.clock.now += 101

    # Bob's inbox cleans up expired invitations
    inbox = env.team.list_my_invitations(bob)
    assert len(inbox) == 1
    assert inbox[0].status == "EXPIRED"

    # Expired pending row does NOT block new invitations:
    new_inv = env.team.invite_member(alice, t.id, username="bob")
    assert new_inv.status == "PENDING"
    assert new_inv.id != inv.id


def test_invitation_acceptance_and_rejection(env):
    alice = make_player(env, "alice")
    bob = make_player(env, "bob")
    charlie = make_player(env, "charlie")
    t = env.team.create_team(alice, "knights", "Knights")

    inv = env.team.invite_member(alice, t.id, username="bob")

    # Charlie cannot accept Bob's invitation (IDOR)
    with pytest.raises(PermissionDenied):
        env.team.accept_invitation(charlie, inv.id)

    # Bob accepts invitation
    team, member = env.team.accept_invitation(bob, inv.id)
    assert member.user_id == bob.account.id
    assert member.team_role == "MEMBER"
    assert team.member_count == 2

    # Cannot accept already accepted invitation
    with pytest.raises(TeamConflict, match="not pending"):
        env.team.accept_invitation(bob, inv.id)

    # Invitation declined flow
    inv2 = env.team.invite_member(alice, t.id, username="charlie")
    env.team.decline_invitation(charlie, inv2.id)
    declined = env.connection.execute("SELECT status FROM team_invitations WHERE id=?", (inv2.id,)).fetchone()
    assert declined[0] == "DECLINED"


def test_captain_revokes_invitation(env):
    alice = make_player(env, "alice")
    bob = make_player(env, "bob")
    t = env.team.create_team(alice, "knights", "Knights")
    inv = env.team.invite_member(alice, t.id, username="bob")

    # Captain revokes
    assert env.team.revoke_invitation(alice, t.id, inv.id) is True
    revoked = env.connection.execute("SELECT status FROM team_invitations WHERE id=?", (inv.id,)).fetchone()
    assert revoked[0] == "REVOKED"

    # Bob cannot accept revoked invitation
    with pytest.raises(TeamConflict, match="not pending"):
        env.team.accept_invitation(bob, inv.id)


def test_members_list_history_and_leave(env):
    alice = make_player(env, "alice")
    bob = make_player(env, "bob")
    t = env.team.create_team(alice, "knights", "Knights")
    inv = env.team.invite_member(alice, t.id, username="bob")
    env.team.accept_invitation(bob, inv.id)

    members = env.team.list_members(alice, t.id)
    assert len(members) == 2
    assert [m.username for m in members] == ["alice", "bob"]

    # Bob leaves the team
    env.clock.now += 50
    assert env.team.leave_team(bob, t.id) is True

    # Active members list only has Alice
    active_members = env.team.list_members(alice, t.id, include_history=False)
    assert len(active_members) == 1
    assert active_members[0].username == "alice"

    # Full history shows Bob with left_at
    history = env.team.list_members(alice, t.id, include_history=True)
    assert len(history) == 2
    bob_m = next(m for m in history if m.username == "bob")
    assert bob_m.left_at == env.clock.now

    # Captain Alice cannot leave without transferring or archiving
    with pytest.raises(TeamConflict, match="Captain cannot leave"):
        env.team.leave_team(alice, t.id)


def test_remove_member(env):
    alice = make_player(env, "alice")
    bob = make_player(env, "bob")
    t = env.team.create_team(alice, "knights", "Knights")
    inv = env.team.invite_member(alice, t.id, username="bob")
    env.team.accept_invitation(bob, inv.id)

    # Bob cannot remove Alice
    with pytest.raises(TeamPermissionDenied):
        env.team.remove_member(bob, t.id, alice.account.id)

    # Alice cannot remove herself (must transfer or archive)
    with pytest.raises(TeamConflict, match="Captain cannot be removed"):
        env.team.remove_member(alice, t.id, alice.account.id)

    # Alice removes Bob
    assert env.team.remove_member(alice, t.id, bob.account.id) is True
    assert len(env.team.list_members(alice, t.id)) == 1


def test_transfer_captain_succession(env):
    alice = make_player(env, "alice")
    bob = make_player(env, "bob")
    t = env.team.create_team(alice, "knights", "Knights")
    inv = env.team.invite_member(alice, t.id, username="bob")
    env.team.accept_invitation(bob, inv.id)

    # Transfer captaincy to Bob
    demoted, promoted = env.team.transfer_captain(alice, t.id, bob.account.id)
    assert demoted.user_id == alice.account.id and demoted.team_role == "MEMBER"
    assert promoted.user_id == bob.account.id and promoted.team_role == "CAPTAIN"

    # Verify team captain is now Bob
    team_now = env.team.get_team(alice, t.id)
    assert team_now.captain_id == bob.account.id

    # Alice is now MEMBER, cannot perform Captain actions
    charlie = make_player(env, "charlie")
    with pytest.raises(TeamPermissionDenied):
        env.team.invite_member(alice, t.id, username="charlie")

    # Bob is now CAPTAIN, can perform Captain actions
    new_inv = env.team.invite_member(bob, t.id, username="charlie")
    assert new_inv.status == "PENDING"


def test_archive_team_terminates_memberships_and_invitations(env):
    alice = make_player(env, "alice")
    bob = make_player(env, "bob")
    charlie = make_player(env, "charlie")
    t = env.team.create_team(alice, "knights", "Knights")
    inv_bob = env.team.invite_member(alice, t.id, username="bob")
    env.team.accept_invitation(bob, inv_bob.id)
    inv_charlie = env.team.invite_member(alice, t.id, username="charlie")

    # Alice archives the team
    archived = env.team.archive_team(alice, t.id)
    assert archived.status == "ARCHIVED"
    assert archived.member_count == 0

    # Active memberships terminated
    active = env.connection.execute(
        "SELECT count(*) FROM team_memberships WHERE team_id = ? AND left_at IS NULL",
        (t.id,)).fetchone()[0]
    assert active == 0

    # Pending invitations revoked
    charlie_inv = env.connection.execute("SELECT status FROM team_invitations WHERE id=?", (inv_charlie.id,)).fetchone()[0]
    assert charlie_inv == "REVOKED"

    # Alice and Bob can now join or create other teams!
    t2 = env.team.create_team(alice, "new-team", "New Team")
    assert t2.slug == "new-team"

    # Mutations on archived team rejected
    with pytest.raises(TeamConflict, match="archived"):
        env.team.update_team(alice, t.id, display_name="Renamed")
    with pytest.raises(TeamConflict, match="archived"):
        env.team.invite_member(alice, t.id, username="bob")


def test_admin_recovery_when_captain_disabled(env):
    alice = make_player(env, "alice")
    bob = make_player(env, "bob")
    t = env.team.create_team(alice, "knights", "Knights")
    inv = env.team.invite_member(alice, t.id, username="bob")
    env.team.accept_invitation(bob, inv.id)

    # Admin disables Alice (the Captain)
    env.auth.disable_account(env.admin, alice.account.id)

    # Alice cannot act (session revoked/disabled)
    with pytest.raises(PermissionDenied):
        env.team.update_team(alice, t.id, display_name="Test")

    # Admin performs recovery captain transfer to Bob
    demoted, promoted = env.team.admin_transfer_captain(env.admin, t.id, bob.account.id)
    assert promoted.user_id == bob.account.id and promoted.team_role == "CAPTAIN"

    # Admin does NOT become team member
    admin_m = env.connection.execute(
        "SELECT 1 FROM team_memberships WHERE user_id = ? AND left_at IS NULL",
        (env.admin.account.id,)).fetchone()
    assert admin_m is None

    # Bob can now run the team as Captain!
    charlie = make_player(env, "charlie")
    inv_c = env.team.invite_member(bob, t.id, username="charlie")
    assert inv_c.status == "PENDING"

    # Admin inspection
    admin_team_view = env.team.admin_get_team(env.admin, t.id)
    assert admin_team_view["team"].slug == "knights"
    assert len(admin_team_view["members"]) == 2


def test_transaction_rollback_when_audit_fails(env, monkeypatch):
    alice = make_player(env, "alice")
    original_audit = env.team._audit

    def failing_audit(*args, **kwargs):
        raise sqlite3.OperationalError("Simulated audit write failure")

    monkeypatch.setattr(env.team, "_audit", failing_audit)

    with pytest.raises(sqlite3.OperationalError, match="Simulated audit write failure"):
        env.team.create_team(alice, "doomed-team", "Doomed Team")

    # Verify atomic rollback: neither team nor membership was created!
    assert env.connection.execute("SELECT count(*) FROM teams WHERE slug='doomed-team'").fetchone()[0] == 0
    assert env.connection.execute("SELECT count(*) FROM team_memberships WHERE user_id=?", (alice.account.id,)).fetchone()[0] == 0


def test_stale_or_revoked_session_rejected(env):
    alice = make_player(env, "alice")
    t = env.team.create_team(alice, "knights", "Knights")

    # Revoke all sessions for Alice
    env.auth.revoke_all(alice)

    # Alice's stale Principal cannot mutate the team
    with pytest.raises(PermissionDenied):
        env.team.update_team(alice, t.id, display_name="New Name")


def test_normalize_invitee_username_and_global_eligibility(env):
    captain = make_player(env, "alice")
    dotted = make_player(env, "john.doe")
    under = make_player(env, "john_doe")
    other = make_player(env, "other")
    team = env.team.create_team(captain, "username-qa", "Username QA")
    assert env.team.invite_member(captain, team.id, username=dotted.account.username).status == "PENDING"
    assert env.team.invite_member(captain, team.id, username=under.account.username).status == "PENDING"
    env.team.create_team(other, "other-qa", "Other QA")
    with pytest.raises(TeamConflict, match="active team"):
        env.team.invite_member(captain, team.id, username="other")


def test_expired_accept_persists_status(env):
    captain = make_player(env, "alice")
    invitee = make_player(env, "bob")
    team = env.team.create_team(captain, "expire-qa", "Expire QA")
    inv = env.team.invite_member(captain, team.id, username="bob", ttl_seconds=1)
    env.clock.now += 2
    with pytest.raises(InvalidInvitation):
        env.team.accept_invitation(invitee, inv.id)
    status = env.connection.execute("SELECT status FROM team_invitations WHERE id=?", (inv.id,)).fetchone()[0]
    assert status == "EXPIRED"


def test_admin_recovery_denies_healthy_captain(env):
    captain = make_player(env, "alice")
    member = make_player(env, "bob")
    team = env.team.create_team(captain, "recovery-qa", "Recovery QA")
    inv = env.team.invite_member(captain, team.id, username="bob")
    env.team.accept_invitation(member, inv.id)
    with pytest.raises(TeamConflict, match="Active Captain"):
        env.team.admin_transfer_captain(env.admin, team.id, member.account.id)

"""Phase 4.2C1: Team HTTP integration.

Exposes Team lifecycle, membership, invitations and RBAC under account-only namespaces.
Integrates with AccountAuthBoundary, CSRF protection, and worker thread execution.
"""
from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import Field

from .auth_http import StrictBody, authenticate_account, runtime_for
from .team_service import (
    InvalidInvitation, Team, TeamConflict, TeamInvitation, TeamMember,
    TeamNotFound, TeamPermissionDenied, TeamService, TeamValidationError
)


class CreateTeamBody(StrictBody):
    slug: str = Field(min_length=3, max_length=48)
    display_name: str = Field(min_length=1, max_length=64)


class UpdateTeamBody(StrictBody):
    display_name: str = Field(min_length=1, max_length=64)


class InviteMemberBody(StrictBody):
    username: str = Field(min_length=3, max_length=32)


class TransferCaptainBody(StrictBody):
    new_captain_user_id: str = Field(min_length=1, max_length=128)


class TeamPolicyBody(StrictBody):
    max_members: int = Field(strict=True, ge=2, le=20)


def require_empty(body):
    if body:
        raise HTTPException(422, "Request body must be an empty JSON object")


def team_json(team: Team) -> dict:
    return {
        "id": team.id,
        "slug": team.slug,
        "display_name": team.display_name,
        "status": team.status,
        "created_by": team.created_by,
        "created_at": team.created_at,
        "updated_at": team.updated_at,
        "captain_id": team.captain_id,
        "member_count": team.member_count,
        "max_members": team.max_members,
    }


def member_json(member: TeamMember) -> dict:
    return {
        "id": member.id,
        "team_id": member.team_id,
        "user_id": member.user_id,
        "username": member.username,
        "display_name": member.display_name,
        "team_role": member.team_role,
        "joined_at": member.joined_at,
        "left_at": member.left_at,
    }


def invitation_json(invitation: TeamInvitation) -> dict:
    return {
        "id": invitation.id,
        "team_id": invitation.team_id,
        "team_slug": invitation.team_slug,
        "team_display_name": invitation.team_display_name,
        "invited_user_id": invitation.invited_user_id,
        "invited_username": invitation.invited_username,
        "invited_by": invitation.invited_by,
        "invited_by_username": invitation.invited_by_username,
        "status": invitation.status,
        "created_at": invitation.created_at,
        "expires_at": invitation.expires_at,
        "responded_at": invitation.responded_at,
    }


async def run_team(runtime, operation):
    def work(auth, conn):
        try:
            return operation(auth, conn)
        except TeamNotFound as exc:
            raise HTTPException(404, str(exc)) from None
        except TeamPermissionDenied as exc:
            raise HTTPException(403, str(exc)) from None
        except TeamConflict as exc:
            raise HTTPException(409, str(exc)) from None
        except TeamValidationError as exc:
            raise HTTPException(422, str(exc)) from None
        except InvalidInvitation as exc:
            raise HTTPException(400, str(exc)) from None

    return await runtime.run(work)


def install_team_http(app):
    router = APIRouter()

    async def policy_operation(request, audience, limit=None):
        actor, _ = await authenticate_account(request, audience, csrf=limit is not None)
        runtime = runtime_for(request)
        return await run_team(runtime, lambda auth, conn: (
            TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).policy(actor)
            if limit is None else TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).set_member_limit(actor, limit)))

    @router.get('/api/admin/team-policy')
    async def admin_policy(request: Request):
        return await policy_operation(request, 'ADMIN')

    @router.get('/api/player/team-policy')
    async def player_policy(request: Request):
        return await policy_operation(request, 'PLAYER')

    @router.put('/api/admin/team-policy')
    async def change_policy(body: TeamPolicyBody, request: Request):
        return await policy_operation(request, 'ADMIN', body.max_members)

    # --- Player Endpoints ---

    @router.get("/api/player/team")
    async def get_my_team(request: Request):
        principal, _ = await authenticate_account(request, "PLAYER", csrf=False)
        runtime = runtime_for(request)
        my_team = await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).get_my_team(principal)
        )
        if not my_team:
            return {"team": None, "my_role": None, "my_membership_id": None}
        return {
            "team": team_json(my_team.team),
            "my_role": my_team.my_role,
            "my_membership_id": my_team.my_membership_id,
        }

    @router.post("/api/player/teams", status_code=201)
    async def create_team(body: CreateTeamBody, request: Request):
        principal, _ = await authenticate_account(request, "PLAYER", csrf=True)
        runtime = runtime_for(request)
        team = await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).create_team(
                principal, body.slug, body.display_name
            )
        )
        return {
            "team": team_json(team),
            "my_role": "CAPTAIN",
        }

    @router.get("/api/player/teams/{team_id}")
    async def get_team(team_id: str, request: Request):
        principal, _ = await authenticate_account(request, "PLAYER", csrf=False)
        runtime = runtime_for(request)
        team = await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).get_team(
                principal, team_id
            )
        )
        return {"team": team_json(team)}

    @router.patch("/api/player/teams/{team_id}")
    async def update_team(team_id: str, body: UpdateTeamBody, request: Request):
        principal, _ = await authenticate_account(request, "PLAYER", csrf=True)
        runtime = runtime_for(request)
        team = await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).update_team(
                principal, team_id, display_name=body.display_name
            )
        )
        return {"team": team_json(team)}

    @router.post("/api/player/teams/{team_id}/activate")
    async def activate_team(team_id: str, request: Request, body: dict = Body(default={})):
        require_empty(body)
        principal, _ = await authenticate_account(request, "PLAYER", csrf=True)
        runtime = runtime_for(request)
        team = await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).activate_team(
                principal, team_id
            )
        )
        return {"team": team_json(team)}

    @router.post("/api/player/teams/{team_id}/archive")
    async def archive_team(team_id: str, request: Request, body: dict = Body(default={})):
        require_empty(body)
        principal, _ = await authenticate_account(request, "PLAYER", csrf=True)
        runtime = runtime_for(request)
        team = await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).archive_team(
                principal, team_id
            )
        )
        return {"team": team_json(team)}

    @router.get("/api/player/teams/{team_id}/members")
    async def list_team_members(team_id: str, request: Request, include_history: bool = Query(False)):
        principal, _ = await authenticate_account(request, "PLAYER", csrf=False)
        runtime = runtime_for(request)
        members = await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).list_members(
                principal, team_id, include_history=include_history
            )
        )
        return {"members": [member_json(m) for m in members]}

    @router.post("/api/player/teams/{team_id}/invitations", status_code=201)
    async def invite_member(team_id: str, body: InviteMemberBody, request: Request):
        principal, _ = await authenticate_account(request, "PLAYER", csrf=True)
        runtime = runtime_for(request)
        invitation = await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).invite_member(
                principal, team_id, username=body.username
            )
        )
        return {"invitation": invitation_json(invitation)}

    @router.get("/api/player/team-invitations")
    async def list_my_invitations(request: Request):
        principal, _ = await authenticate_account(request, "PLAYER", csrf=False)
        runtime = runtime_for(request)
        invitations = await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).list_my_invitations(
                principal
            )
        )
        return {"invitations": [invitation_json(i) for i in invitations]}

    @router.post("/api/player/team-invitations/{invitation_id}/accept")
    async def accept_invitation(invitation_id: str, request: Request, body: dict = Body(default={})):
        require_empty(body)
        principal, _ = await authenticate_account(request, "PLAYER", csrf=True)
        runtime = runtime_for(request)
        team, member = await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).accept_invitation(
                principal, invitation_id
            )
        )
        return {
            "team": team_json(team),
            "my_role": member.team_role,
            "my_membership_id": member.id,
        }

    @router.post("/api/player/team-invitations/{invitation_id}/decline")
    async def decline_invitation(invitation_id: str, request: Request, body: dict = Body(default={})):
        require_empty(body)
        principal, _ = await authenticate_account(request, "PLAYER", csrf=True)
        runtime = runtime_for(request)
        await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).decline_invitation(
                principal, invitation_id
            )
        )
        return {"declined": True}

    @router.post("/api/player/teams/{team_id}/invitations/{invitation_id}/revoke")
    async def revoke_invitation(team_id: str, invitation_id: str, request: Request, body: dict = Body(default={})):
        require_empty(body)
        principal, _ = await authenticate_account(request, "PLAYER", csrf=True)
        runtime = runtime_for(request)
        await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).revoke_invitation(
                principal, team_id, invitation_id
            )
        )
        return {"revoked": True}

    @router.post("/api/player/teams/{team_id}/captain-transfer")
    async def transfer_captain(team_id: str, body: TransferCaptainBody, request: Request):
        principal, _ = await authenticate_account(request, "PLAYER", csrf=True)
        runtime = runtime_for(request)
        demoted, promoted = await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).transfer_captain(
                principal, team_id, body.new_captain_user_id
            )
        )
        return {
            "transferred": True,
            "demoted": member_json(demoted),
            "promoted": member_json(promoted),
        }

    @router.post("/api/player/teams/{team_id}/members/{user_id}/remove")
    async def remove_member(team_id: str, user_id: str, request: Request, body: dict = Body(default={})):
        require_empty(body)
        principal, _ = await authenticate_account(request, "PLAYER", csrf=True)
        runtime = runtime_for(request)
        await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).remove_member(
                principal, team_id, user_id
            )
        )
        return {"removed": True, "user_id": user_id}

    @router.post("/api/player/teams/{team_id}/leave")
    async def leave_team(team_id: str, request: Request, body: dict = Body(default={})):
        require_empty(body)
        principal, _ = await authenticate_account(request, "PLAYER", csrf=True)
        runtime = runtime_for(request)
        await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).leave_team(
                principal, team_id
            )
        )
        return {"left": True}

    # --- Admin Endpoints ---

    @router.get("/api/admin/teams")
    async def admin_list_teams(request: Request):
        principal, _ = await authenticate_account(request, "ADMIN", csrf=False)
        runtime = runtime_for(request)
        teams = await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).admin_list_teams(
                principal
            )
        )
        policy = await run_team(runtime,lambda auth,conn:TeamService(conn,runtime.writer,auth_service=auth,clock=runtime.settings.clock).policy(principal))
        return {"teams": [team_json(t) for t in teams], "policy": policy}

    @router.get("/api/admin/teams/{team_id}")
    async def admin_get_team(team_id: str, request: Request):
        principal, _ = await authenticate_account(request, "ADMIN", csrf=False)
        runtime = runtime_for(request)
        data = await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).admin_get_team(
                principal, team_id
            )
        )
        return {
            "team": team_json(data["team"]),
            "members": [member_json(m) for m in data["members"]],
            "invitations": [invitation_json(i) for i in data["invitations"]],
        }

    @router.post("/api/admin/teams/{team_id}/archive")
    async def admin_archive_team(team_id: str, request: Request, body: dict = Body(default={})):
        require_empty(body)
        principal, _ = await authenticate_account(request, "ADMIN", csrf=True)
        runtime = runtime_for(request)
        team = await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).archive_team(
                principal, team_id
            )
        )
        return {"team": team_json(team)}

    @router.post("/api/admin/teams/{team_id}/captain-transfer")
    async def admin_transfer_captain(team_id: str, body: TransferCaptainBody, request: Request):
        principal, _ = await authenticate_account(request, "ADMIN", csrf=True)
        runtime = runtime_for(request)
        demoted, promoted = await run_team(
            runtime,
            lambda auth, conn: TeamService(conn, runtime.writer, auth_service=auth, clock=runtime.settings.clock).admin_transfer_captain(
                principal, team_id, body.new_captain_user_id
            )
        )
        return {
            "transferred": True,
            "demoted": member_json(demoted) if demoted else None,
            "promoted": member_json(promoted),
        }

    app.include_router(router)

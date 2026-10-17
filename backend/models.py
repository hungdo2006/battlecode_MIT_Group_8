from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Literal

class MatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bot_a: str
    bot_b: str
    game_id: str | None = None
    game: str | None = None  # Accept older clients/replays without coupling core to a game.
    rules: dict | None = None

    @model_validator(mode="after")
    def matching_ids(self):
        if self.game_id and self.game and self.game_id != self.game:
            raise ValueError("game_id và game phải giống nhau nếu cùng được gửi.")
        return self


class GameSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    game_id: str


class SessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str):
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Nickname không được chứa ký tự điều khiển.")
        value = " ".join(value.split())
        if not 1 <= len(value) <= 32:
            raise ValueError("Nickname cần từ 1 đến 32 ký tự.")
        return value


class OrganizerCode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=256)


class ActiveBotSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bot_id: str = Field(min_length=1, max_length=64)


class InvitationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    player_a_id: str = Field(min_length=1, max_length=64)
    player_b_id: str = Field(min_length=1, max_length=64)

class TournamentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    format: Literal[
        "single_elimination",
        "double_elimination",
        "round_robin",
    ]
    player_ids: list[str] = Field(min_length=2)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str):
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Tên giải không được chứa ký tự điều khiển.")
        value = " ".join(value.split())
        if not value:
            raise ValueError("Tên giải không được để trống.")
        return value

    @field_validator("player_ids")
    @classmethod
    def validate_player_ids(cls, value: list[str]):
        if any(not player_id or len(player_id) > 64 for player_id in value):
            raise ValueError("Mã người chơi không hợp lệ.")
        if len(value) != len(set(value)):
            raise ValueError("Không được chọn trùng người chơi.")
        return value

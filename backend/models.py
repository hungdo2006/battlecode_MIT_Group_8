from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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

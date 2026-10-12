from pydantic import BaseModel, ConfigDict, model_validator


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

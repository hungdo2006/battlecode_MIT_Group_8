"""Fail-closed compatibility check for compiled bots against the current sandbox.

The runtime image is supplied by the private Controller, never by a Player.
A missing current image or missing historical artifact image requires rebuilding
the bot; the original bot JSON, frozen snapshots and replays remain untouched.
"""


def artifact_current(store, bot):
    if not bot or bot.get("status") != "ready":
        return False
    provider = getattr(store, "sandbox_image_for_game", None)
    if provider is None:
        # No sandbox runtime in legacy/in-memory fixtures.
        return True
    image = provider(bot.get("game_id"))
    return bool(image and bot.get("image") == image)


def public_bot_status(store, bot):
    if bot.get("status") == "ready" and not artifact_current(store, bot):
        return "needs_rebuild"
    return bot.get("status")

"""Stable user-facing command remains a pure alias to the deployed runner."""

from scripts import arena_operator


def test_operator_forwards_cli_arguments_without_changing_runtime(monkeypatch):
    calls = []

    def legacy_main(argv=None):
        calls.append(argv)
        return 1

    monkeypatch.setattr(arena_operator.b15_pilot_runner, "main", legacy_main)
    assert arena_operator.main(["status"]) == 1
    assert arena_operator.main(["switch", "--target", "local",
                                "--backup-directory", ".runner-switch/example"]) == 1
    assert calls == [
        ["status"],
        ["switch", "--target", "local",
         "--backup-directory", ".runner-switch/example"],
    ]

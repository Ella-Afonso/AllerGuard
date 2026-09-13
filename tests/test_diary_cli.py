"""Owner confirmation stays explicit and separate from the original daily fact."""

import pytest

from src.config import Settings
from src.runtime.approve import main
from src.runtime.daily_diary import run_daily_diary
from src.tools.audit import list_history
from tests.audit_support import NOW


def test_show_never_confirms_and_explicit_confirm_reuses(
    audit_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    run_daily_diary("demo-cafe", NOW.date(), now=NOW, settings=audit_settings)
    assert main(["diary", "show", str(NOW.date())], now=NOW, settings=audit_settings) == 0
    assert "await explicit owner confirmation" in capsys.readouterr().out
    assert len(list_history("demo-cafe", audit_settings)) == 1
    args = ["diary", "confirm", str(NOW.date()), "--opening", "confirmed", "--closing", "confirmed"]
    assert main(args, now=NOW, settings=audit_settings) == 0
    before = list_history("demo-cafe", audit_settings)
    assert len(before) == 2
    assert main(args, now=NOW, settings=audit_settings) == 0
    assert list_history("demo-cafe", audit_settings) == before


def test_missing_answers_note_or_diary_fail(audit_settings: Settings) -> None:
    assert main(["diary", "show", str(NOW.date())], now=NOW, settings=audit_settings) == 2
    run_daily_diary("demo-cafe", NOW.date(), now=NOW, settings=audit_settings)
    assert main(["diary", "confirm", str(NOW.date())], now=NOW, settings=audit_settings) == 2
    assert (
        main(
            [
                "diary",
                "confirm",
                str(NOW.date()),
                "--opening",
                "exception",
                "--closing",
                "confirmed",
            ],
            now=NOW,
            settings=audit_settings,
        )
        == 2
    )
    assert len(list_history("demo-cafe", audit_settings)) == 1

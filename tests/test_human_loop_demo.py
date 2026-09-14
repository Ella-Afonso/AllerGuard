"""Offline human-loop demonstration acceptance tests."""

from __future__ import annotations

from pathlib import Path

from scripts.demo_human_loop import run_demo


def test_human_loop_demo_has_simulated_11_to_14_and_3_to_0_transitions(
    tmp_path: Path, capsys
) -> None:
    report = tmp_path / "human-loop.html"
    assert run_demo(report) == 0
    output = capsys.readouterr().out
    assert "NO AWS" in output
    assert "NO BEDROCK" in output
    assert "Initial read-back: 11 audit events, 3 pending, 3 simulated notifications." in output
    assert (
        "Replay read-back: 11 audit events, 3 pending, 3 simulated notifications total." in output
    )
    assert "Decision read-back: 14 audit events, 0 pending, 3 decisions." in output
    assert "Final read-back: 14 audit events, 0 pending, 3 simulated notifications total." in output
    assert "does not execute the action pack" in output
    html = report.read_text(encoding="utf-8")
    assert html.count('<article class="event ') == 14
    assert "simulated" in html
    assert "Owner decision recorded" in html
    assert "No customer, stock or action-pack execution was performed." in html

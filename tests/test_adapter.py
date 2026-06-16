import json
from pathlib import Path

import pytest

from engine.adapter import _extract, _parse_progress, build_solver_input
from engine.models import SolveRequest

FIXTURE = Path(__file__).parent / "fixtures" / "output_result.json"


def _request(**overrides: object) -> SolveRequest:
    base: dict[str, object] = {
        "oop_range": "AA,KK,AKs",
        "ip_range": "QQ,JJ,AQs",
        "board": "Qs Jh 2h",
        "pot": 50,
        "effective_stack": 200,
    }
    base.update(overrides)
    return SolveRequest.model_validate(base)


def test_build_solver_input_has_required_directives() -> None:
    text = build_solver_input(_request(), Path("/tmp/out.json"))
    assert "set_pot 50" in text
    assert "set_board Qs,Jh,2h" in text
    assert "set_range_oop AA,KK,AKs" in text
    assert "set_bet_sizes oop,flop,bet,50" in text
    assert "set_bet_sizes ip,river,allin" in text
    assert text.strip().endswith("dump_result /tmp/out.json")
    # build_tree must precede start_solve.
    assert text.index("build_tree") < text.index("start_solve")


def test_build_solver_input_custom_sizes() -> None:
    text = build_solver_input(_request(bet_sizes=[33, 75], raise_sizes=[50]), Path("/tmp/o.json"))
    assert "set_bet_sizes oop,flop,bet,33,75" in text
    assert "set_bet_sizes ip,turn,raise,50" in text


def test_extract_strategies_from_fixture() -> None:
    tree = json.loads(FIXTURE.read_text())
    oop, ip, oop_actions, ip_actions = _extract(tree)

    assert oop_actions == ["CHECK", "BET 50"]
    assert oop["AsAh"] == {"CHECK": 0.20, "BET 50": 0.80}
    # IP node is reached through the passive (CHECK) branch.
    assert ip_actions == ["CHECK", "BET 50"]
    assert ip["AdAs"] == {"CHECK": 0.10, "BET 50": 0.90}


def test_parse_progress() -> None:
    # Matches TexasSolver's real console output format (note the "precent" typo).
    stdout = (
        "Iter: 10\nplayer 0 exploitability 3.1\nTotal exploitability 1.23 precent\n"
        "Iter: 30\nplayer 0 exploitability 1.0\nTotal exploitability 0.40 precent"
    )
    exploitability, iterations = _parse_progress(stdout)
    assert exploitability == 0.40
    assert iterations == 30


@pytest.mark.parametrize("bad_board", ["Qs Jh", "Qs Jh 2h 2h", "Zs Jh 2h"])
def test_board_validation(bad_board: str) -> None:
    with pytest.raises(ValueError):
        _request(board=bad_board)

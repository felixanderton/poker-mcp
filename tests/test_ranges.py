import pytest

from engine.ranges import combo_to_class, grid_class, list_presets, normalize_range


@pytest.mark.parametrize(
    ("combo", "expected"),
    [
        ("AsAh", "AA"),
        ("AhKh", "AKs"),
        ("AhKs", "AKo"),
        ("KhAh", "AKs"),  # order-independent
        ("7c7d", "77"),
        ("2c3d", "32o"),
    ],
)
def test_combo_to_class(combo: str, expected: str) -> None:
    assert combo_to_class(combo) == expected


def test_grid_layout_corners() -> None:
    assert grid_class(0, 0) == "AA"
    assert grid_class(12, 12) == "22"
    assert grid_class(0, 12) == "A2s"  # upper triangle -> suited
    assert grid_class(12, 0) == "A2o"  # lower triangle -> offsuit


def test_normalize_range_roundtrip() -> None:
    assert normalize_range(" AA, KK ,AKs:0.5 ") == "AA,KK,AKs:0.5"


@pytest.mark.parametrize("bad", ["", "ZZ", "AKx", "AA:abc"])
def test_normalize_range_rejects_bad(bad: str) -> None:
    with pytest.raises(ValueError):
        normalize_range(bad)


def test_presets_present() -> None:
    presets = list_presets()
    assert "RFI_BTN" in presets
    for value in presets.values():
        normalize_range(value)  # every preset must be valid solver syntax

from rotation.r3_market_follow import choose_market_mints
from rotation.r3_registry import ResearchRegistry


def test_market_selection_keeps_observed_pair_legs_and_excludes_reserves():
    registry = ResearchRegistry.load("config/r3-universe.json")
    selected = choose_market_mints("data/r3-20260927", registry, max_mints=6)
    assert 2 <= len(selected) <= 6
    assert set(selected) <= registry.eligible_mints(
        __import__("datetime").datetime.fromisoformat(registry.known_at)
    )
    assert registry.by_symbol["WIF"]["mint"] in selected
    assert registry.by_symbol["FARTCOIN"]["mint"] in selected
    two = choose_market_mints("data/r3-20260927", registry, max_mints=2)
    assert set(two) == {
        registry.by_symbol["WIF"]["mint"],
        registry.by_symbol["FARTCOIN"]["mint"],
    }

"""Chaos knobs must be stable: the same order is late on every run, or a rerun proves nothing."""

from replayer.replay import picks


def test_zero_ratio_never_picks() -> None:
    assert not any(picks(f"order{i}", "late", 0.0) for i in range(500))


def test_full_ratio_always_picks() -> None:
    assert all(picks(f"order{i}", "late", 1.0) for i in range(500))


def test_selection_is_stable_across_calls() -> None:
    keys = [f"order{i}" for i in range(200)]
    first = [picks(k, "late", 0.3) for k in keys]
    second = [picks(k, "late", 0.3) for k in keys]

    assert first == second


def test_salt_separates_the_two_knobs() -> None:
    keys = [f"order{i}" for i in range(500)]
    late = {k for k in keys if picks(k, "late", 0.5)}
    duplicate = {k for k in keys if picks(k, "duplicate", 0.5)}

    # Same ratio, different knob: the two sets must not be the same orders every time.
    assert late != duplicate


def test_share_is_close_to_the_requested_ratio() -> None:
    keys = [f"order-{i}" for i in range(5000)]
    share = sum(picks(k, "late", 0.2) for k in keys) / len(keys)

    assert 0.17 < share < 0.23

from pathlib import Path

from bili_tracker.application.discovery import (
    BoundedRefreshLoop,
    Candidate,
    QuantitativeRanker,
    RefreshLimits,
)


def test_ranker_scores_following_bonus_and_caps_at_100():
    candidate = Candidate(
        "a",
        "Python course",
        "https://example.invalid/a",
        views=10**12,
        following=True,
        is_hot=True,
    )
    result = QuantitativeRanker().rank([candidate], query="Python")[0]
    assert result.quantitative_score <= 100
    assert result.final_score == 100


def test_ranker_keeps_exclusion_reason_and_hot_candidate():
    short = Candidate("a", "short", "u", duration_seconds=5, views=10**6)
    hot = Candidate("b", "hot", "u", duration_seconds=5, views=10**6, is_hot=True)
    result = QuantitativeRanker().rank([short, hot])
    assert result[0].id == "b"
    assert short.filter_reason == "duration_below_minimum"


def test_refresh_loop_persists_and_obeys_task_limit(tmp_path: Path):
    candidates = [
        Candidate(
            str(index), "ok", "u", duration_seconds=100, views=10**6, is_hot=True
        )
        for index in range(20)
    ]
    state_path = tmp_path / "refresh.json"
    loop = BoundedRefreshLoop(
        RefreshLimits(max_rounds=10, per_round=5, max_tasks=3), state_path=state_path
    )
    added = []
    provider = type("Provider", (), {"candidates": lambda self, query: candidates})()
    state = loop.run(provider, added.append)
    assert len(added) == 3
    assert state.stop_reason == "task_limit"
    assert state_path.is_file()
    restored = BoundedRefreshLoop(RefreshLimits(max_rounds=10, max_tasks=5), state_path=state_path)
    assert restored.state.tasks_created == 3


def test_stop_prevents_next_round():
    loop = BoundedRefreshLoop(RefreshLimits())
    loop.stop()
    called = []
    provider = type(
        "Provider", (), {"candidates": lambda self, query: called.append(query) or []}
    )()
    state = loop.run(provider, lambda item: None)
    assert state.stop_reason == "stopped_by_user"
    assert called == []

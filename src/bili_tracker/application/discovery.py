from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class Candidate:
    id: str
    title: str
    url: str
    duration_seconds: float | None = None
    views: int = 0
    following: bool = False
    is_hot: bool = False
    quantitative_score: float = 0.0
    remote_score: float | None = None
    final_score: float = 0.0
    filter_reason: str | None = None
    prompt_version: str | None = None


class CandidateProvider(Protocol):
    def candidates(self, query: str) -> list[Candidate]: ...


class Ranker(Protocol):
    def rank(self, candidates: list[Candidate]) -> list[Candidate]: ...


@dataclass(frozen=True)
class RankingPolicy:
    min_duration_seconds: float = 30.0
    threshold: float = 50.0
    keyword_weight: float = 30.0
    popularity_weight: float = 25.0
    freshness_weight: float = 40.0
    following_bonus: float = 5.0


class QuantitativeRanker:
    id = "quantitative-v1"

    def __init__(self, policy: RankingPolicy | None = None) -> None:
        self.policy = policy or RankingPolicy()

    def rank(self, candidates: list[Candidate], *, query: str = "") -> list[Candidate]:
        query_terms = {term.casefold() for term in query.split() if term.strip()}
        ranked: list[Candidate] = []
        for candidate in candidates:
            if (
                candidate.duration_seconds is not None
                and candidate.duration_seconds < self.policy.min_duration_seconds
                and not candidate.is_hot
            ):
                candidate.filter_reason = "duration_below_minimum"
                candidate.final_score = 0.0
                ranked.append(candidate)
                continue
            title = candidate.title.casefold()
            keyword = (
                self.policy.keyword_weight
                if query_terms and any(term in title for term in query_terms)
                else 0.0
            )
            popularity = min(
                self.policy.popularity_weight, math.log10(max(candidate.views, 1)) * 4.0
            )
            freshness = self.policy.freshness_weight if candidate.is_hot else 0.0
            candidate.quantitative_score = min(100.0, keyword + popularity + freshness)
            candidate.final_score = min(
                100.0,
                candidate.quantitative_score
                + (self.policy.following_bonus if candidate.following else 0.0),
            )
            if candidate.final_score < self.policy.threshold and not candidate.is_hot:
                candidate.filter_reason = "below_threshold"
            ranked.append(candidate)
        return sorted(ranked, key=lambda item: (-item.final_score, item.id))


@dataclass(frozen=True)
class RefreshLimits:
    max_rounds: int = 3
    per_round: int = 20
    max_tasks: int = 50
    max_failures: int = 10
    time_limit_seconds: float = 300.0


@dataclass
class RefreshState:
    round: int = 0
    tasks_created: int = 0
    failures: int = 0
    stopped: bool = False
    stop_reason: str | None = None


class BoundedRefreshLoop:
    def __init__(self, limits: RefreshLimits, *, state_path: Path | None = None) -> None:
        self.limits = limits
        self.state_path = state_path
        self.state = self._load()
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()
        self.state.stopped = True
        self.state.stop_reason = "stopped_by_user"
        self._save()

    def run(
        self,
        provider: CandidateProvider,
        enqueue: Any,
        *,
        query: str = "",
        ranker: QuantitativeRanker | None = None,
    ) -> RefreshState:
        started = time.monotonic()
        ranker = ranker or QuantitativeRanker()
        while self.state.round < self.limits.max_rounds and not self.state.stopped:
            if self.stop_event.is_set():
                self.stop()
                break
            if time.monotonic() - started >= self.limits.time_limit_seconds:
                self.state.stopped = True
                self.state.stop_reason = "time_limit"
                break
            if self.state.tasks_created >= self.limits.max_tasks:
                self.state.stopped = True
                self.state.stop_reason = "task_limit"
                break
            self.state.round += 1
            try:
                candidates = ranker.rank(provider.candidates(query), query=query)
            except Exception:
                self.state.failures += 1
                if self.state.failures >= self.limits.max_failures:
                    self.state.stopped = True
                    self.state.stop_reason = "failure_limit"
                self._save()
                continue
            accepted = [candidate for candidate in candidates if not candidate.filter_reason]
            for candidate in accepted[: self.limits.per_round]:
                if self.state.tasks_created >= self.limits.max_tasks or self.stop_event.is_set():
                    break
                try:
                    enqueue(candidate)
                    self.state.tasks_created += 1
                except Exception:
                    self.state.failures += 1
                    if self.state.failures >= self.limits.max_failures:
                        self.state.stopped = True
                        self.state.stop_reason = "failure_limit"
                        break
            self._save()
        if not self.state.stopped and self.state.round >= self.limits.max_rounds:
            self.state.stopped = True
            self.state.stop_reason = "round_limit"
            self._save()
        return self.state

    def _load(self) -> RefreshState:
        if not self.state_path or not self.state_path.is_file():
            return RefreshState()
        try:
            values = json.loads(self.state_path.read_text(encoding="utf-8"))
            return RefreshState(
                **{key: values[key] for key in asdict(RefreshState()) if key in values}
            )
        except (OSError, ValueError, TypeError):
            return RefreshState()

    def _save(self) -> None:
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self.state), indent=2), encoding="utf-8")
        temp.replace(self.state_path)

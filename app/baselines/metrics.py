"""Metrics layer — hand-rolled AUROC, AUPR (average precision), Brier.

Pure functions, no sklearn. Degenerate inputs (empty, single-class targets)
return None so callers report `n/a` instead of a fake number.
"""

from __future__ import annotations

from collections.abc import Sequence


def auroc(scores: Sequence[float], targets: Sequence[int]) -> float | None:
    """Tie-aware AUROC via the Mann-Whitney rank formula."""
    positives = sum(targets)
    negatives = len(targets) - positives
    if positives == 0 or negatives == 0:
        return None

    # Average ranks (1-based), ties share the mean rank of their block.
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        mean_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = mean_rank
        i = j + 1

    rank_sum_positives = sum(rank for rank, t in zip(ranks, targets, strict=True) if t == 1)
    u = rank_sum_positives - positives * (positives + 1) / 2
    return u / (positives * negatives)


def aupr(scores: Sequence[float], targets: Sequence[int]) -> float | None:
    """Average precision: mean of precision at each positive, descending by score."""
    positives = sum(targets)
    if positives == 0 or not targets:
        return None

    by_score = sorted(zip(scores, targets, strict=True), key=lambda st: -st[0])
    seen_positives = 0
    precision_sum = 0.0
    for rank, (_, target) in enumerate(by_score, start=1):
        if target == 1:
            seen_positives += 1
            precision_sum += seen_positives / rank
    return precision_sum / positives


def brier(scores: Sequence[float], targets: Sequence[int]) -> float | None:
    """Mean squared error of probabilistic scores against binary outcomes."""
    if not targets:
        return None
    return sum((s - t) ** 2 for s, t in zip(scores, targets, strict=True)) / len(targets)

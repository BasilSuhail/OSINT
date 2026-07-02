"""WS-E forward prediction journal — the accuracy scoreboard.

Every forecast is logged with a server-stamped issued_at before the outcome is
known (immutable once issued), graded exactly once when its window matures,
and accumulated into a track record. Pure functions per layer (emit, grade,
scoreboard), side effects at the edges, mirroring `app/labels/`.
"""

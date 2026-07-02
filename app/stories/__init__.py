"""WS-A story clustering — one row per real-world story.

Groups news events from all feeds into stories via tf-idf token vectors and
greedy leader clustering (stories-v1.0, deliberately basic — the vectorizer
is swappable for embeddings later behind the same interface). Unlocks WS-B
(disagreement index) and WS-C (corroboration score).
"""

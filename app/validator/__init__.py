"""WS-G local LLM validator — another noisy annotator, never a judge (#378, plan on #282).

Guardrail, non-negotiable: nothing downstream consumes these rows until the
model's agreement with a human-checked sample is measured and published.
"""

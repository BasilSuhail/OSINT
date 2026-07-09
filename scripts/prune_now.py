import json

from app.db import session_scope
from app.housekeeping import run_retention_and_cap, vacuum_events

with session_scope() as s:
    result = run_retention_and_cap(s)
    bind = s.get_bind()
print(json.dumps(result))
try:
    vacuum_events(bind)
except Exception as exc:  # vacuum is best-effort; deletes already committed
    print(f"warning: VACUUM failed (non-fatal): {exc}")

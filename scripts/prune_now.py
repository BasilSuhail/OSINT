from app.db import session_scope
from app.housekeeping import prune_events
import json

with session_scope() as s:
    print(json.dumps(prune_events(s)))

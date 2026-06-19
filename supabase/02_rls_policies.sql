-- Row Level Security policies for public-facing tables.
--
-- Two tables are read by the public frontend through the Supabase anon key:
--   - events  (raw OSINT events, used for map markers + article cards)
--   - scores  (composite stress index per (country, month))
--
-- Everything else stays private. The service_role bypasses RLS and continues
-- to read / write everything for the Python backend.
--
-- How to use:
--   1. Run `supabase/01_schema.sql` first
--   2. Supabase SQL Editor → paste this file → Run
--   3. Verify policies under Database → Authentication → Policies

-- ---------------------------------------------------------------------------
-- events
-- ---------------------------------------------------------------------------
ALTER TABLE public.events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS events_anon_read ON public.events;
CREATE POLICY events_anon_read
    ON public.events
    FOR SELECT
    TO anon, authenticated
    USING (true);

-- ---------------------------------------------------------------------------
-- scores
-- ---------------------------------------------------------------------------
ALTER TABLE public.scores ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS scores_anon_read ON public.scores;
CREATE POLICY scores_anon_read
    ON public.scores
    FOR SELECT
    TO anon, authenticated
    USING (true);

-- ---------------------------------------------------------------------------
-- Everything else: enable RLS without policies → no access from anon /
-- authenticated. Service role bypasses RLS so the Python backend still works.
-- ---------------------------------------------------------------------------
ALTER TABLE public.labels             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ingest_health      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ingest_failures    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dead_letter_queue  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.housekeeping_runs  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications      ENABLE ROW LEVEL SECURITY;

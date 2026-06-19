import { createClient, type SupabaseClient } from "@supabase/supabase-js"

const url = process.env.NEXT_PUBLIC_SUPABASE_URL
// Accept either the publishable key (preferred) or the legacy anon key name.
const key =
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ??
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

export const isSupabaseConfigured = Boolean(url && key)

let client: SupabaseClient | null = null

/**
 * Returns a singleton Supabase client, or null if env vars are missing.
 * Read-only anon access; realtime enabled.
 */
export function getSupabase(): SupabaseClient | null {
  if (!isSupabaseConfigured) return null
  if (client) return client
  client = createClient(url as string, key as string, {
    auth: { persistSession: false },
    realtime: { params: { eventsPerSecond: 20 } },
  })
  return client
}

import { API_BASE } from "./apiClient"

export interface StoryRow {
  id: string
  title: string
  first_seen: string
  last_seen: string
  member_count: number
  outlet_count: number
  method_version: string
}

export async function fetchTopStories(hours = 24, limit = 100): Promise<StoryRow[]> {
  const res = await fetch(`${API_BASE}/stories/top?hours=${hours}&limit=${limit}`)
  if (!res.ok) throw new Error(`GET /stories/top ${res.status}`)
  return (await res.json()) as StoryRow[]
}

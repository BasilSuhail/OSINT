import { format, isSameDay, subDays } from "date-fns"
import type { AskExchange, BrainSource } from "./apiClient"

/** One ask-the-brain exchange in the Situation chat transcript (#439). */
export interface ChatMessage {
  question: string
  answer: string
  sources: BrainSource[]
  draft: boolean
}

export type ChatAction =
  | { type: "ask"; question: string }
  | { type: "delta"; text: string }
  | { type: "sources"; sources: BrainSource[] }
  | { type: "finalize"; answer: string; sources: BrainSource[] }
  | { type: "fail" }
  | { type: "clear" }
  | { type: "restore"; messages: ChatMessage[] }

export const MAX_CHAT_MESSAGES = 200

export const OFFLINE_ANSWER = "The brain is offline right now."

/** Live-feed order: most recent activity first; ties keep API (loudness) order. */
export function sortByActivity<T extends { last_seen: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => b.last_seen.localeCompare(a.last_seen))
}

/**
 * Split an activity-sorted list at the yesterday/older boundary: `recent` is
 * today + yesterday (shown by default), `older` hides behind the expander.
 */
export function splitRecent<T extends { last_seen: string }>(
  rows: T[],
  now: Date = new Date(),
): { recent: T[]; older: T[] } {
  const cut = rows.findIndex(
    (r) =>
      !isSameDay(new Date(r.last_seen), now) &&
      !isSameDay(new Date(r.last_seen), subDays(now, 1)),
  )
  if (cut === -1) return { recent: rows, older: [] }
  return { recent: rows.slice(0, cut), older: rows.slice(cut) }
}

/**
 * Per-row day labels for an activity-sorted list: null while the day continues,
 * "yesterday" / "wed 8 jul" where a row starts an earlier day. Today never gets
 * a marker — the list opens on it.
 */
export function dayMarkers<T extends { last_seen: string }>(
  rows: T[],
  now: Date = new Date(),
): (string | null)[] {
  let prev: Date = now
  return rows.map((row) => {
    const day = new Date(row.last_seen)
    const marker = isSameDay(day, prev)
      ? null
      : isSameDay(day, subDays(now, 1))
        ? "yesterday"
        : format(day, "EEE d MMM").toLowerCase()
    prev = day
    return marker
  })
}

function patchLast(state: ChatMessage[], patch: (last: ChatMessage) => ChatMessage): ChatMessage[] {
  if (state.length === 0) return state
  return [...state.slice(0, -1), patch(state[state.length - 1])]
}

export function chatReducer(state: ChatMessage[], action: ChatAction): ChatMessage[] {
  switch (action.type) {
    case "ask":
      return [...state, { question: action.question, answer: "", sources: [], draft: true }]
    case "delta":
      return patchLast(state, (m) => ({ ...m, answer: `${m.answer}${action.text}` }))
    case "sources":
      return patchLast(state, (m) => ({ ...m, sources: action.sources }))
    case "finalize":
      return patchLast(state, (m) => ({
        ...m,
        answer: action.answer,
        sources: action.sources,
        draft: false,
      }))
    case "fail":
      return patchLast(state, (m) => ({ ...m, answer: OFFLINE_ANSWER, draft: false }))
    case "clear":
      return []
    case "restore":
      return action.messages
  }
}

export interface OriginGroup<T> {
  origin: string | null
  members: T[]
}

/** Members bucketed by outlet origin country, biggest bloc first, unknown last (#448). */
export function groupByOrigin<T extends { origin_country: string | null }>(
  members: T[],
): OriginGroup<T>[] {
  const buckets = new Map<string | null, T[]>()
  for (const m of members) {
    const key = m.origin_country
    const list = buckets.get(key) ?? []
    list.push(m)
    buckets.set(key, list)
  }
  return [...buckets.entries()]
    .map(([origin, grouped]) => ({ origin, members: grouped }))
    .sort((a, b) => {
      if (a.origin === null) return 1
      if (b.origin === null) return -1
      return b.members.length - a.members.length
    })
}

const HISTORY_MAX = 3
//: Matches the backend AskExchange answer cap headroom (#444).
const HISTORY_ANSWER_CHARS = 2000

/** Recent finalized exchanges to send with an ask, so follow-ups stay anchored. */
export function askHistory(messages: ChatMessage[]): AskExchange[] {
  return messages
    .filter((m) => !m.draft && m.answer && m.answer !== OFFLINE_ANSWER)
    .slice(-HISTORY_MAX)
    .map((m) => ({ question: m.question, answer: m.answer.slice(0, HISTORY_ANSWER_CHARS) }))
}

/** Restore a transcript from sessionStorage; corrupt or foreign data yields []. */
export function parseChatStorage(raw: string | null): ChatMessage[] {
  if (!raw) return []
  let data: unknown
  try {
    data = JSON.parse(raw)
  } catch {
    return []
  }
  if (!Array.isArray(data)) return []
  const valid = data.every(
    (m) =>
      typeof m === "object" &&
      m !== null &&
      typeof (m as ChatMessage).question === "string" &&
      typeof (m as ChatMessage).answer === "string" &&
      Array.isArray((m as ChatMessage).sources),
  )
  if (!valid) return []
  //: A draft persisted mid-stream must not reload stuck on "drafting".
  return (data as ChatMessage[]).slice(-MAX_CHAT_MESSAGES).map((m) => ({ ...m, draft: false }))
}

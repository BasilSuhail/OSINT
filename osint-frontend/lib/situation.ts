import { format, isSameDay, subDays } from "date-fns"
import type { AskClaim, AskExchange, AskReasoning, BrainSource } from "./apiClient"

/** One ask-the-brain exchange in the Situation chat transcript (#439). */
export interface ChatMessage {
  question: string
  answer: string
  sources: BrainSource[]
  /** Weak-retrieval fallback (#459): near-misses shown separately, never as evidence. */
  closest: BrainSource[]
  /** Chip fuel (#476): sentence→story mapping + retrieval reasoning. */
  claims: AskClaim[]
  reasoning: AskReasoning | null
  draft: boolean
}

export type ChatAction =
  | { type: "ask"; question: string }
  | { type: "delta"; text: string }
  | { type: "sources"; sources: BrainSource[] }
  | {
      type: "finalize"
      answer: string
      sources: BrainSource[]
      closest: BrainSource[]
      claims: AskClaim[]
      reasoning: AskReasoning | null
    }
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

/** One renderable piece of an answer line (#476). */
export type AnswerSegment =
  | { type: "text"; text: string }
  | { type: "source"; n: number }
  | { type: "thinking"; claim: number }

const CITATION_RE = /\[(\d+)\]/g

/**
 * Answer → lines of segments for chip rendering (#476): each [n] becomes a
 * clickable (source) chip; a line carrying an unsupported claim (the brain's
 * own analysis) gets a trailing (thinking) chip. Empty lines mark paragraph
 * breaks.
 */
export function answerLines(answer: string, claims: AskClaim[]): AnswerSegment[][] {
  const unsupported = claims
    .map((claim, index) => ({ claim, index }))
    .filter(({ claim }) => !claim.supported && claim.text)
  return answer.split("\n").map((line) => {
    const segments: AnswerSegment[] = []
    let last = 0
    for (const match of line.matchAll(CITATION_RE)) {
      const at = match.index ?? 0
      if (at > last) segments.push({ type: "text", text: line.slice(last, at) })
      segments.push({ type: "source", n: Number(match[1]) })
      last = at + match[0].length
    }
    if (last < line.length) segments.push({ type: "text", text: line.slice(last) })
    for (const { claim, index } of unsupported) {
      if (line.includes(claim.text)) segments.push({ type: "thinking", claim: index })
    }
    return segments
  })
}

function patchLast(state: ChatMessage[], patch: (last: ChatMessage) => ChatMessage): ChatMessage[] {
  if (state.length === 0) return state
  return [...state.slice(0, -1), patch(state[state.length - 1])]
}

export function chatReducer(state: ChatMessage[], action: ChatAction): ChatMessage[] {
  switch (action.type) {
    case "ask":
      return [
        ...state,
        {
          question: action.question,
          answer: "",
          sources: [],
          closest: [],
          claims: [],
          reasoning: null,
          draft: true,
        },
      ]
    case "delta":
      return patchLast(state, (m) => ({ ...m, answer: `${m.answer}${action.text}` }))
    case "sources":
      return patchLast(state, (m) => ({ ...m, sources: action.sources }))
    case "finalize":
      return patchLast(state, (m) => ({
        ...m,
        answer: action.answer,
        sources: action.sources,
        closest: action.closest,
        claims: action.claims,
        reasoning: action.reasoning,
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

//: Fixed voice order for the story card's per-class view (#488).
export const VOICE_ORDER = ["mainstream", "regional", "state", "independent"] as const

export interface VoiceGroup<T> {
  voice: string
  members: T[]
}

/** Members bucketed by outlet class in fixed VOICE_ORDER (#488); classes the
 *  registry doesn't know come last, unlabeled members count as mainstream. */
export function groupByVoice<T extends { outlet_class?: string }>(members: T[]): VoiceGroup<T>[] {
  const buckets = new Map<string, T[]>()
  for (const m of members) {
    const key = m.outlet_class || "mainstream"
    const list = buckets.get(key) ?? []
    list.push(m)
    buckets.set(key, list)
  }
  const known: VoiceGroup<T>[] = VOICE_ORDER.filter((v) => buckets.has(v)).map((voice) => ({
    voice,
    members: buckets.get(voice) as T[],
  }))
  const rest: VoiceGroup<T>[] = [...buckets.keys()]
    .filter((k) => !(VOICE_ORDER as readonly string[]).includes(k))
    .sort()
    .map((voice) => ({ voice, members: buckets.get(voice) as T[] }))
  return [...known, ...rest]
}

/** Single-voice caveat (#488): non-null when one class tells the story alone —
 *  mirrors the prompt's "state-only is never confirmed" rule. */
export function singleVoiceCaveat(groups: VoiceGroup<unknown>[]): string | null {
  if (groups.length !== 1) return null
  return `single-voice coverage — only ${groups[0].voice} outlets tell this`
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
  //: Transcripts saved before #459/#476 lack the newer fields — default them.
  return (data as ChatMessage[]).slice(-MAX_CHAT_MESSAGES).map((m) => ({
    ...m,
    closest: m.closest ?? [],
    claims: m.claims ?? [],
    reasoning: m.reasoning ?? null,
    draft: false,
  }))
}

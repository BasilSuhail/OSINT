"use client"

/**
 * The right-hand reader on /news — one story, opened beside the list.
 *
 * Same read as the console's story card (`/stories/{id}/detail`), laid out for
 * reading rather than for glancing: the gist first, then who told it and what
 * they disagreed about, then every filing with a link out.
 *
 * Voices are grouped by outlet class, not by outlet, because the question a
 * reader has is "who is telling me this" — five feeds owned by one company are
 * one answer, not five.
 */

import useSWR from "swr"
import { X } from "lucide-react"
import { fetchStoryDetail, type StoryDetail, type StoryMember } from "@/lib/analytics"
import { relativeAge } from "@/lib/newsRanking"

//: Fixed order so the reader's eye lands in the same place every time, rather
//: than following whatever the window happened to contain.
const CLASS_ORDER = ["independent", "mainstream", "regional", "state"] as const

function Label({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-3 font-mono text-[10px] uppercase tracking-[0.22em] text-neutral-500">
      {children}
    </h3>
  )
}

function Voice({ member, now }: { member: StoryMember; now: number }) {
  const body = (
    <>
      <span className="block font-mono text-[10px] uppercase tracking-[0.12em] text-neutral-500">
        {member.outlet}
        {member.origin_country ? ` · ${member.origin_country}` : ""} ·{" "}
        {relativeAge(member.occurred_at, now)}
      </span>
      <span className="mt-1 block text-[0.95rem] leading-snug text-neutral-200">
        {member.title}
      </span>
    </>
  )
  return (
    <li className="border-t border-neutral-800/60 py-3 first:border-t-0">
      {member.url ? (
        <a
          href={member.url}
          target="_blank"
          rel="noreferrer"
          className="block transition-colors hover:text-cyan-300"
        >
          {body}
        </a>
      ) : (
        body
      )}
    </li>
  )
}

export function StoryReader({
  storyId,
  now,
  onClose,
}: {
  storyId: string
  /** The page's clock, so every age on screen is measured from one instant. */
  now: number
  onClose: () => void
}) {
  const { data, error } = useSWR<StoryDetail>(
    storyId ? `news:detail:${storyId}` : null,
    () => fetchStoryDetail(storyId),
    { revalidateOnFocus: false },
  )

  if (error) {
    return (
      <div className="rounded-2xl border border-neutral-800 bg-neutral-900/40 p-6">
        <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-red-400/80">
          this story could not be read
        </p>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="rounded-2xl border border-neutral-800 bg-neutral-900/40 p-6">
        <p className="text-neutral-600">opening…</p>
      </div>
    )
  }

  const byClass = new Map<string, StoryMember[]>()
  for (const member of data.members) {
    const key = member.outlet_class || "other"
    byClass.set(key, [...(byClass.get(key) ?? []), member])
  }
  const groups = [...byClass.entries()].sort(
    (a, b) =>
      CLASS_ORDER.indexOf(a[0] as (typeof CLASS_ORDER)[number]) -
      CLASS_ORDER.indexOf(b[0] as (typeof CLASS_ORDER)[number]),
  )

  return (
    <article className="rounded-2xl border border-neutral-800 bg-neutral-900/40 p-7">
      <div className="mb-6 flex items-start justify-between gap-4">
        <h1 className="font-serif text-[1.65rem] leading-[1.22] tracking-[-0.014em] text-neutral-50">
          {data.title}
        </h1>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close story (esc)"
          className="mt-1 shrink-0 rounded-md border border-neutral-800 p-1.5 text-neutral-500 transition-colors hover:border-cyan-500/60 hover:text-cyan-300"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {data.gist && (
        <p className="mb-7 text-[1.02rem] leading-relaxed text-neutral-300">{data.gist}</p>
      )}

      <dl className="mb-8 grid grid-cols-3 gap-4 border-y border-neutral-800 py-4">
        {[
          ["owners", String(data.owner_count)],
          ["outlets", String(data.outlet_count)],
          [
            "corroboration",
            data.corroboration === null ? "unscored" : data.corroboration.toFixed(2),
          ],
        ].map(([label, value]) => (
          <div key={label}>
            <dt className="font-mono text-[10px] uppercase tracking-[0.14em] text-neutral-500">
              {label}
            </dt>
            <dd className="mt-1 font-serif text-[1.3rem] tabular-nums text-neutral-100">
              {value}
            </dd>
          </div>
        ))}
      </dl>

      {data.framing?.synthesis && (
        <section className="mb-8">
          <Label>How the telling differs</Label>
          <p className="text-[0.95rem] leading-relaxed text-neutral-300">
            {data.framing.synthesis.a} reads {data.framing.synthesis.a_tone};{" "}
            {data.framing.synthesis.b} reads {data.framing.synthesis.b_tone}.
          </p>
        </section>
      )}

      <section>
        <Label>
          Voices · {data.members.length} filing{data.members.length === 1 ? "" : "s"}
        </Label>
        {groups.map(([outletClass, members]) => (
          <div key={outletClass} className="mb-5">
            <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.16em] text-neutral-600">
              {outletClass} ×{members.length}
            </p>
            <ul>
              {members.map((member, i) => (
                <Voice key={`${member.source}-${i}`} member={member} now={now} />
              ))}
            </ul>
          </div>
        ))}
      </section>
    </article>
  )
}

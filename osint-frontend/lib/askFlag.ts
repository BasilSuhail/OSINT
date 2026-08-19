/**
 * Whether this build answers questions.
 *
 * Read once, at module scope, because Next inlines `process.env.NEXT_PUBLIC_*`
 * at build time — there is nothing to re-read later and nothing to react to.
 * The parse is separate from the read so it can be tested without a build.
 *
 * Off is explicit, and the words that spell it are pydantic's, because the API
 * reads the same setting through a pydantic bool and the two must not disagree
 * about what the operator wrote. `false`, `f`, `no`, `n`, `off` and `0` are off
 * on both sides; `true`, `t`, `yes`, `y`, `on` and `1` are on. An absent key or
 * an empty one is on, which is what lets `env.example` ship the setting blank:
 * a laptop that never touches it keeps the console it had.
 *
 * A typo is not harmless, and this used to say it was. Pydantic accepts neither
 * side's vocabulary loosely — `ASK_ENABLED=maybe` raises on startup and the API
 * does not come up at all — so a value this function does not recognise never
 * reaches a running console. Returning "on" for one is the safer of two answers
 * nobody will see rather than a promise that the mistake costs nothing.
 */
const FALSEY = new Set(["false", "f", "no", "n", "off", "0"])

export function parseAskEnabled(raw: string | undefined): boolean {
  const value = (raw ?? "").trim().toLowerCase()
  if (!value) return true
  return !FALSEY.has(value)
}

export const ASK_ENABLED = parseAskEnabled(process.env.NEXT_PUBLIC_ASK_ENABLED)

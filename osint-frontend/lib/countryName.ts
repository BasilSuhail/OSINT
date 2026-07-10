/** ISO2 → full English country name via the built-in Intl API (no dependency).
 * Unknown or malformed codes fall back to the code itself — never a guess. */

const display =
  typeof Intl !== "undefined" && "DisplayNames" in Intl
    ? new Intl.DisplayNames(["en"], { type: "region", fallback: "none" })
    : null

export function countryName(code: string): string {
  if (!code || code.length !== 2 || !display) return code
  try {
    return display.of(code.toUpperCase()) ?? code
  } catch {
    return code
  }
}

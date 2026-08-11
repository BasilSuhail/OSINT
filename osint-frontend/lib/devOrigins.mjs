/**
 * Which hosts may load this dev server's own `/_next/*` resources (#930).
 *
 * `next dev` refuses those requests from any host that is not localhost. On a
 * shared stack that reached the other device as a page shell, a `webpack-hmr`
 * websocket retrying forever, and a map stuck on "initialising" — a dashboard
 * that looks broken and says nothing about why.
 *
 * Plain `.mjs` rather than TypeScript because `next.config.mjs` imports it
 * directly, before any transpiler is in play.
 */

/**
 * @param {string | undefined} raw comma-separated hosts, bare: no scheme, no port
 * @returns {string[]} hosts to allow, empty when nothing is being shared
 */
export const parseDevOrigins = (raw) =>
  (raw ?? "")
    .split(",")
    .map((host) => host.trim())
    .filter(Boolean)

import { dirname } from "path"
import { fileURLToPath } from "url"

import { parseDevOrigins } from "./lib/devOrigins.mjs"

const __dirname = dirname(fileURLToPath(import.meta.url))
const apiPort = process.env.API_PORT || "8000"
const apiProxyTarget = (
  process.env.API_PROXY_TARGET || `http://127.0.0.1:${apiPort}`
).replace(/\/+$/, "")

// Empty unless the stack is being shared (#930). `make share` sets
// LAN_SHARE_HOST to the address it is publishing on, for that run only, so the
// default allow-list stays empty — see lib/devOrigins.mjs.
const allowedDevOrigins = parseDevOrigins(process.env.LAN_SHARE_HOST)

/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiProxyTarget}/:path*`,
      },
    ]
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  turbopack: {
    root: __dirname,
  },
  // Hide the floating "N" Next dev indicator badge in the bottom corner.
  devIndicators: false,
}

export default nextConfig

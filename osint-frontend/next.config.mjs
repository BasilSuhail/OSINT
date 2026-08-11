import { dirname } from "path"
import { fileURLToPath } from "url"

import { parseDevOrigins } from "./lib/devOrigins.mjs"

const __dirname = dirname(fileURLToPath(import.meta.url))

// Empty unless the stack is being shared (#930). `make share` sets
// LAN_SHARE_HOST to the address it is publishing on, for that run only, so the
// default allow-list stays empty — see lib/devOrigins.mjs.
const allowedDevOrigins = parseDevOrigins(process.env.LAN_SHARE_HOST)

/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins,
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

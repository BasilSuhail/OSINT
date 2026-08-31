import type { MetadataRoute } from "next"

const background = "#0a0a0a"

function icons(name: "osint" | "news"): NonNullable<MetadataRoute.Manifest["icons"]> {
  return [
    {
      src: `/app-icons/${name}-192.png`,
      sizes: "192x192",
      type: "image/png",
      purpose: "any",
    },
    {
      src: `/app-icons/${name}-512.png`,
      sizes: "512x512",
      type: "image/png",
      purpose: "any",
    },
    {
      src: `/app-icons/${name}-maskable-512.png`,
      sizes: "512x512",
      type: "image/png",
      purpose: "maskable",
    },
  ]
}

export const consoleManifest: MetadataRoute.Manifest = {
  id: "/",
  name: "OSINT",
  short_name: "OSINT",
  description: "Real-time open-source intelligence world monitor.",
  start_url: "/",
  scope: "/",
  display: "standalone",
  background_color: background,
  theme_color: background,
  icons: icons("osint"),
}

export const newsManifest: MetadataRoute.Manifest = {
  id: "/news",
  name: "OSINT News",
  short_name: "OSINT News",
  description: "A focused reading view of current open-source reporting.",
  start_url: "/news",
  scope: "/news",
  display: "standalone",
  background_color: background,
  theme_color: background,
  icons: icons("news"),
}

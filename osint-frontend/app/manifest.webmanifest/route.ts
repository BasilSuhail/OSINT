import { consoleManifest } from "@/lib/appManifests"

export const dynamic = "force-static"

export function GET() {
  return Response.json(consoleManifest, {
    headers: {
      "Cache-Control": "public, max-age=3600",
      "Content-Type": "application/manifest+json",
    },
  })
}

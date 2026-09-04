import { newsManifest } from "@/lib/appManifests"

export const dynamic = "force-static"

export function GET() {
  return Response.json(newsManifest, {
    headers: {
      "Cache-Control": "public, max-age=3600",
      "Content-Type": "application/manifest+json",
    },
  })
}

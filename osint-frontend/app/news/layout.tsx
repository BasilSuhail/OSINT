import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "OSINT News",
  description: "A focused reading view of current open-source reporting.",
  manifest: "/news/manifest.webmanifest",
  icons: {
    apple: [
      {
        url: "/app-icons/news-apple-touch.png",
        sizes: "180x180",
        type: "image/png",
      },
    ],
  },
  appleWebApp: {
    capable: true,
    title: "OSINT News",
    statusBarStyle: "black-translucent",
  },
  other: {
    "apple-mobile-web-app-capable": "yes",
  },
}

export default function NewsLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children
}

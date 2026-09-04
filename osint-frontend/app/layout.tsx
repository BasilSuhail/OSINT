import type { Metadata, Viewport } from "next"
import "./globals.css"
import { RealtimeProvider } from "./providers"

export const metadata: Metadata = {
  title: "OSINT World Monitor · LIVE",
  description:
    "Real-time open-source intelligence dashboard. A filterable world map, scrubbable through time.",
  manifest: "/manifest.webmanifest",
  icons: {
    apple: [
      {
        url: "/app-icons/osint-apple-touch.png",
        sizes: "180x180",
        type: "image/png",
      },
    ],
  },
  appleWebApp: {
    capable: true,
    title: "OSINT",
    statusBarStyle: "black-translucent",
  },
  other: {
    "apple-mobile-web-app-capable": "yes",
  },
}

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#0a0a0a",
  width: "device-width",
  initialScale: 1,
  //: The map owns pinch. A page that zooms underneath it is a page whose
  //: controls drift off the edge with no way back.
  maximumScale: 1,
  //: The console draws to the edges of a phone, so the notch and the home
  //: indicator overlap it unless `env(safe-area-inset-*)` resolves to real
  //: numbers — which is what this turns on (#942). The bar and the sheet
  //: read them; nothing else needs to.
  viewportFit: "cover",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className="bg-neutral-950 font-sans text-neutral-100 antialiased">
        <RealtimeProvider>{children}</RealtimeProvider>
      </body>
    </html>
  )
}

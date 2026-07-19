import type { Metadata, Viewport } from "next"
import "./globals.css"
import { RealtimeProvider } from "./providers"

export const metadata: Metadata = {
  title: "OSINT World Monitor · LIVE",
  description:
    "Real-time open-source intelligence dashboard. A filterable world map, scrubbable through time.",
}

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#0a0a0a",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
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

"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

const TABS = [
  { href: "/", label: "console" },
  { href: "/stories", label: "stories" },
] as const

/** Compact page tabs for the top status bar. */
export function ConsoleNav() {
  const pathname = usePathname()
  return (
    <nav className="flex shrink-0 items-center gap-1">
      {TABS.map((tab) => {
        const active = pathname === tab.href
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={
              active
                ? "rounded-sm bg-neutral-800 px-1.5 py-0.5 font-mono text-[8px] uppercase tracking-wide text-cyan-300"
                : "rounded-sm px-1.5 py-0.5 font-mono text-[8px] uppercase tracking-wide text-neutral-500 hover:text-neutral-200"
            }
          >
            {tab.label}
          </Link>
        )
      })}
    </nav>
  )
}

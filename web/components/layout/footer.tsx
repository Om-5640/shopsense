import Link from 'next/link'
import { Github } from 'lucide-react'

export function Footer() {
  const year = new Date().getFullYear()

  return (
    <footer className="relative border-t border-white/[0.05] mt-auto">
      <div className="max-w-7xl mx-auto px-4 py-6">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4">

          {/* Brand */}
          <div className="flex items-center gap-2.5">
            <div className="relative w-6 h-6 flex-shrink-0">
              <div className="absolute inset-0 rounded-full border border-violet-400/60" />
              <div className="absolute inset-[3px] rounded-full border border-violet-400/40" />
              <div className="absolute inset-[6px] rounded-full bg-violet-400/70" />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-[#A1A1AA]">ShopResearch</span>
              <span className="text-[#3F3F46] text-xs">—</span>
              <span className="text-xs text-[#3F3F46]">AI-powered product research</span>
            </div>
          </div>

          {/* Links */}
          <div className="flex items-center gap-1">
            <Link
              href="https://github.com/Om-5640/shopsense"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-[#52525B] hover:text-[#A1A1AA] hover:bg-white/[0.04] transition-all duration-200"
            >
              <Github className="w-3.5 h-3.5" />
              Source
            </Link>
            <Link
              href="/history"
              className="px-3 py-1.5 rounded-lg text-xs text-[#52525B] hover:text-[#A1A1AA] hover:bg-white/[0.04] transition-all duration-200"
            >
              History
            </Link>
            <Link
              href="/memory"
              className="px-3 py-1.5 rounded-lg text-xs text-[#52525B] hover:text-[#A1A1AA] hover:bg-white/[0.04] transition-all duration-200"
            >
              Memory
            </Link>
            <Link
              href="/settings"
              className="px-3 py-1.5 rounded-lg text-xs text-[#52525B] hover:text-[#A1A1AA] hover:bg-white/[0.04] transition-all duration-200"
            >
              Settings
            </Link>
          </div>

          {/* Copyright */}
          <span className="text-xs text-[#3F3F46] font-mono tabular-nums">
            © {year}
          </span>

        </div>
      </div>
    </footer>
  )
}

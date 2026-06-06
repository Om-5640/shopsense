import Link from 'next/link'
import { Github, Zap } from 'lucide-react'

export function Footer() {
  const year = new Date().getFullYear()

  return (
    <footer className="relative mt-auto">
      {/* Gradient top border — replaces flat border-t */}
      <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-violet-500/25 to-transparent" />
      {/* Subtle surface lift */}
      <div className="absolute inset-0 bg-gradient-to-b from-white/[0.012] to-transparent pointer-events-none" />

      <div className="relative max-w-7xl mx-auto px-4 py-7">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-5">

          {/* Brand */}
          <div className="flex items-center gap-3">
            <div className="relative w-7 h-7 flex-shrink-0">
              <div className="absolute inset-0 rounded-full border border-violet-400/55" />
              <div className="absolute inset-[3px] rounded-full border border-violet-400/35" />
              <div className="absolute inset-[6px] rounded-full bg-violet-400/65" />
            </div>
            <div className="flex flex-col">
              <span className="text-sm font-semibold gradient-text leading-tight">ShopResearch</span>
              <span className="text-[10px] text-[#3F3F46] leading-tight">AI-powered product research</span>
            </div>
          </div>

          {/* Center tagline */}
          <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white/[0.02] border border-white/[0.05]">
            <Zap className="w-3 h-3 text-violet-400/70" />
            <span className="text-[11px] text-[#3F3F46]">
              15 sources · 10 agents · &lt;60s
            </span>
          </div>

          {/* Links + Copyright */}
          <div className="flex items-center gap-3">
            <Link
              href="https://github.com/Om-5640/shopsense"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-[#52525B] hover:text-[#A1A1AA] hover:bg-white/[0.04] border border-transparent hover:border-white/[0.06] transition-all duration-200"
            >
              <Github className="w-3.5 h-3.5" />
              Source
            </Link>
            <span className="text-xs text-[#3F3F46] font-mono tabular-nums select-none">
              © {year}
            </span>
          </div>

        </div>
      </div>
    </footer>
  )
}

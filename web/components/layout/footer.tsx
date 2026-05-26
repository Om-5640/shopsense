import Link from 'next/link'
import { Github, FileText, Twitter } from 'lucide-react'

export function Footer() {
  return (
    <footer className="border-t border-white/[0.06] py-8">
      <div className="max-w-6xl mx-auto px-4">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
          {/* Version */}
          <span className="text-xs font-mono text-[#71717A]">v8.0</span>
          
          {/* Links */}
          <div className="flex items-center gap-6">
            <Link
              href="https://github.com"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 text-sm text-[#71717A] hover:text-[#FAFAFA] transition-colors"
            >
              <Github className="w-4 h-4" />
              <span className="hidden sm:inline">GitHub</span>
            </Link>
            <Link
              href="/docs"
              className="flex items-center gap-2 text-sm text-[#71717A] hover:text-[#FAFAFA] transition-colors"
            >
              <FileText className="w-4 h-4" />
              <span className="hidden sm:inline">Docs</span>
            </Link>
            <Link
              href="https://twitter.com"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 text-sm text-[#71717A] hover:text-[#FAFAFA] transition-colors"
            >
              <Twitter className="w-4 h-4" />
              <span className="hidden sm:inline">Twitter</span>
            </Link>
          </div>
          
          {/* Credit */}
          <span className="text-xs text-[#71717A]">
            Built with AI
          </span>
        </div>
      </div>
    </footer>
  )
}

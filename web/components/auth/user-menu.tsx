'use client'

import { useSession, signIn, signOut } from 'next-auth/react'
import { LogIn, LogOut, Settings, Brain } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import Image from 'next/image'
import Link from 'next/link'

function getInitials(name: string | null | undefined): string {
  if (!name) return '?'
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join('')
}

function Avatar({
  src, name, size = 36,
}: { src?: string | null; name?: string | null; size?: number }) {
  const initials = getInitials(name)
  const px = `${size}px`
  if (src) {
    return (
      <Image
        src={src}
        alt={name ?? 'User avatar'}
        width={size}
        height={size}
        sizes={px}
        className="object-cover w-full h-full"
      />
    )
  }
  return (
    <div
      className="w-full h-full bg-gradient-to-br from-violet-500 to-purple-700 flex items-center justify-center"
      aria-label={name ?? 'User'}
    >
      <span className="text-xs font-semibold text-white select-none">{initials}</span>
    </div>
  )
}

export function UserMenu() {
  const { data: session, status } = useSession()

  if (status === 'loading') {
    return <div className="w-9 h-9 rounded-full bg-white/[0.06] animate-pulse" />
  }

  if (!session) {
    return (
      <Button
        variant="ghost"
        size="sm"
        onClick={() => signIn('google')}
        className="flex items-center gap-2 text-[#71717A] hover:text-[#FAFAFA] hover:bg-white/[0.04] rounded-lg px-3 h-9"
      >
        <LogIn className="w-3.5 h-3.5" />
        <span className="text-xs hidden sm:inline">Sign in</span>
      </Button>
    )
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className="relative w-9 h-9 rounded-full overflow-hidden ring-1 ring-white/[0.12] hover:ring-violet-400/70 transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-500 shadow-md"
          aria-label="Account menu"
        >
          <Avatar src={session.user.image} name={session.user.name} />
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent
        align="end"
        sideOffset={8}
        className="w-56 bg-[#0F0F12] border border-white/[0.08] shadow-2xl rounded-xl p-1"
      >
        {/* Identity header */}
        <div className="flex items-center gap-3 px-3 py-3">
          <div className="relative w-10 h-10 rounded-full overflow-hidden ring-1 ring-white/[0.12] flex-shrink-0">
            <Avatar src={session.user.image} name={session.user.name} size={40} />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium text-[#FAFAFA] truncate leading-tight">
              {session.user.name}
            </p>
            <p className="text-xs text-[#52525B] truncate mt-0.5">{session.user.email}</p>
          </div>
        </div>

        <DropdownMenuSeparator className="bg-white/[0.06] my-1" />

        <DropdownMenuItem
          asChild
          className="text-[#A1A1AA] hover:text-[#FAFAFA] hover:bg-white/[0.04] cursor-pointer gap-2.5 rounded-lg px-3 py-2 text-sm"
        >
          <Link href="/memory">
            <Brain className="w-3.5 h-3.5 flex-shrink-0" />
            My Memory
          </Link>
        </DropdownMenuItem>

        <DropdownMenuItem
          asChild
          className="text-[#A1A1AA] hover:text-[#FAFAFA] hover:bg-white/[0.04] cursor-pointer gap-2.5 rounded-lg px-3 py-2 text-sm"
        >
          <Link href="/settings">
            <Settings className="w-3.5 h-3.5 flex-shrink-0" />
            Settings
          </Link>
        </DropdownMenuItem>

        <DropdownMenuSeparator className="bg-white/[0.06] my-1" />

        <DropdownMenuItem
          onClick={() => signOut({ callbackUrl: '/' })}
          className="text-rose-400/80 hover:text-rose-300 hover:bg-rose-500/[0.08] cursor-pointer gap-2.5 rounded-lg px-3 py-2 text-sm focus:bg-rose-500/[0.08] focus:text-rose-300"
        >
          <LogOut className="w-3.5 h-3.5 flex-shrink-0" />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

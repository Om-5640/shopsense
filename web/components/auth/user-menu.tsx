'use client'

import { useSession, signIn, signOut } from 'next-auth/react'
import { LogIn, LogOut, User } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import Image from 'next/image'

export function UserMenu() {
  const { data: session, status } = useSession()

  if (status === 'loading') {
    return (
      <div className="w-8 h-8 rounded-full bg-white/[0.06] animate-pulse" />
    )
  }

  if (!session) {
    return (
      <Button
        variant="ghost"
        size="sm"
        onClick={() => signIn('google')}
        className="flex items-center gap-2 text-[#71717A] hover:text-[#FAFAFA] hover:bg-white/[0.04] rounded-lg px-3"
      >
        <LogIn className="w-3.5 h-3.5" />
        <span className="text-xs hidden sm:inline">Sign in</span>
      </Button>
    )
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="relative w-8 h-8 rounded-full overflow-hidden border border-white/10 hover:border-violet-400/50 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400">
          {session.user.image ? (
            <Image
              src={session.user.image}
              alt={session.user.name ?? 'User avatar'}
              fill
              className="object-cover"
            />
          ) : (
            <div className="w-full h-full bg-violet-500/30 flex items-center justify-center">
              <User className="w-4 h-4 text-violet-300" />
            </div>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="w-52 bg-[#0F0F12] border-white/[0.08] text-[#FAFAFA]"
      >
        <div className="px-3 py-2">
          <p className="text-sm font-medium truncate">{session.user.name}</p>
          <p className="text-xs text-[#71717A] truncate">{session.user.email}</p>
        </div>
        <DropdownMenuSeparator className="bg-white/[0.06]" />
        <DropdownMenuItem
          onClick={() => signOut({ callbackUrl: '/' })}
          className="text-[#A1A1AA] hover:text-[#FAFAFA] hover:bg-white/[0.04] cursor-pointer gap-2"
        >
          <LogOut className="w-3.5 h-3.5" />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

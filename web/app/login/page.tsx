'use client'

import { signIn, useSession } from 'next-auth/react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useEffect, Suspense } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'

function LoginContent() {
  const { data: session, status } = useSession()
  const router = useRouter()
  const searchParams = useSearchParams()
  const next = searchParams.get('next') ?? '/'

  useEffect(() => {
    if (status === 'authenticated') {
      router.replace(next)
    }
  }, [status, router, next])

  if (status === 'loading' || status === 'authenticated') {
    return (
      <div className="min-h-screen bg-[#08080A] flex items-center justify-center">
        <Loader2 className="w-6 h-6 text-violet-400 animate-spin" />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#08080A] flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex items-center justify-center gap-2.5 mb-8">
          <div className="relative w-10 h-10">
            <div className="absolute inset-0 rounded-full border-2 border-violet-400/80" />
            <div className="absolute inset-2 rounded-full border border-violet-400/60" />
            <div className="absolute inset-4 rounded-full bg-violet-400/80" />
          </div>
          <span className="font-semibold text-xl text-[#FAFAFA] tracking-tight">ShopResearch</span>
        </div>

        <div className="bg-[#0F0F12] border border-white/[0.08] rounded-2xl p-8 shadow-2xl">
          <h1 className="text-lg font-semibold text-[#FAFAFA] text-center mb-1">
            Sign in to your account
          </h1>
          <p className="text-sm text-[#71717A] text-center mb-6">
            Save your research and preferences across devices
          </p>

          <Button
            onClick={() => signIn('google', { callbackUrl: next })}
            className="w-full flex items-center justify-center gap-3 bg-white hover:bg-white/90 text-[#0F0F12] font-medium h-11 rounded-lg transition-colors"
          >
            <svg className="w-5 h-5 flex-shrink-0" viewBox="0 0 24 24">
              <path
                fill="#4285F4"
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
              />
              <path
                fill="#34A853"
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              />
              <path
                fill="#FBBC05"
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"
              />
              <path
                fill="#EA4335"
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
              />
            </svg>
            Continue with Google
          </Button>

          <p className="mt-4 text-center text-xs text-[#52525B]">
            Guest searches work without an account.
            <br />Sign in only to save memory across devices.
          </p>
        </div>
      </div>
    </div>
  )
}

export default function LoginPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-[#08080A] flex items-center justify-center">
        <Loader2 className="w-6 h-6 text-violet-400 animate-spin" />
      </div>
    }>
      <LoginContent />
    </Suspense>
  )
}

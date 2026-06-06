import { auth } from '@/auth'
import { NextResponse } from 'next/server'

export default auth((req) => {
  const isLoggedIn = !!req.auth
  const isMemoryRoute = req.nextUrl.pathname.startsWith('/memory')

  if (isMemoryRoute && !isLoggedIn) {
    const loginUrl = new URL('/login', req.url)
    loginUrl.searchParams.set('next', req.nextUrl.pathname)
    return NextResponse.redirect(loginUrl)
  }

  return NextResponse.next()
})

export const config = {
  // Only hard-block routes that must never be reachable by guests.
  // /memory handles its own unauthenticated UI — no redirect needed.
  matcher: [],
}

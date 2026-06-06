import NextAuth from 'next-auth'
import Google from 'next-auth/providers/google'
import { SignJWT } from 'jose'

const hasGoogleCreds =
  !!process.env.GOOGLE_CLIENT_ID && !!process.env.GOOGLE_CLIENT_SECRET

// Same secret the FastAPI backend uses to verify tokens (PyJWT + HS256).
const _secretBytes = () =>
  new TextEncoder().encode(process.env.NEXTAUTH_SECRET ?? 'dev-insecure-placeholder')

export const { handlers, signIn, signOut, auth } = NextAuth({
  trustHost: true,
  secret: process.env.NEXTAUTH_SECRET ?? 'dev-insecure-placeholder',
  providers: hasGoogleCreds
    ? [
        Google({
          clientId: process.env.GOOGLE_CLIENT_ID!,
          clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
        }),
      ]
    : [],
  pages: {
    signIn: '/login',
  },
  session: {
    strategy: 'jwt',
    maxAge: 30 * 24 * 60 * 60,
  },
  callbacks: {
    // Generate a backend-verifiable HS256 token once and cache it in the JWT
    // cookie. Google's id_token is RS256 signed by Google — the FastAPI backend
    // can't verify it with NEXTAUTH_SECRET+HS256, which caused all 401s that
    // triggered the signOut loop. This token uses the same secret and algorithm
    // so PyJWT.decode(token, NEXTAUTH_SECRET, algorithms=["HS256"]) succeeds.
    async jwt({ token }) {
      if (!token.backendToken) {
        token.backendToken = await new SignJWT({
          sub: token.sub,
          email: token.email,
        })
          .setProtectedHeader({ alg: 'HS256' })
          .setIssuedAt()
          .setExpirationTime('30d')
          .sign(_secretBytes())
      }
      return token
    },
    session({ session, token }) {
      session.user.id = token.sub as string
      session.accessToken = token.backendToken as string
      return session
    },
  },
})

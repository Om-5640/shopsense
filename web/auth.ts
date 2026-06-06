import NextAuth from 'next-auth'
import Google from 'next-auth/providers/google'

const hasGoogleCreds =
  !!process.env.GOOGLE_CLIENT_ID && !!process.env.GOOGLE_CLIENT_SECRET

export const { handlers, signIn, signOut, auth } = NextAuth({
  // trustHost removes the need for explicit NEXTAUTH_URL in dev
  trustHost: true,
  // fallback secret lets the session endpoint respond (not sign in)
  // in dev without a configured secret; replace with a real secret in production
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
    jwt({ token, account }) {
      if (account?.id_token) token.accessToken = account.id_token
      return token
    },
    session({ session, token }) {
      session.user.id = token.sub as string
      session.accessToken = token.accessToken as string
      return session
    },
  },
})

import NextAuth from 'next-auth'
import Google from 'next-auth/providers/google'

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET!,
    }),
  ],
  pages: {
    signIn: '/login',
  },
  session: {
    strategy: 'jwt',
    maxAge: 30 * 24 * 60 * 60, // 30 days
  },
  callbacks: {
    jwt({ token, account }) {
      // Expose Google id_token so backend can verify identity
      if (account?.id_token) {
        token.accessToken = account.id_token
      }
      return token
    },
    session({ session, token }) {
      session.user.id = token.sub as string
      session.accessToken = token.accessToken as string
      return session
    },
  },
})

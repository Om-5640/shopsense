import type { Metadata, Viewport } from 'next'
import { Inter, JetBrains_Mono } from 'next/font/google'
import { Analytics } from '@vercel/analytics/next'
import { Toaster } from 'sonner'
import { SessionProvider } from 'next-auth/react'
import { ThemeProvider } from 'next-themes'
import { AdoptLegacy } from '@/components/auth/adopt-legacy'
import './globals.css'

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
})

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-jetbrains',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'ShopResearch - Find what you should actually buy',
  description: 'Personalized shopping research agent that scrapes Reddit threads and expert reviews, builds a weighted rubric from your priorities, and ranks products by what matters to you.',
  keywords: ['shopping', 'research', 'product recommendations', 'Reddit', 'AI', 'personalized'],
  authors: [{ name: 'ShopResearch' }],
  icons: {
    icon: [
      { url: '/icon-light-32x32.png', media: '(prefers-color-scheme: light)' },
      { url: '/icon-dark-32x32.png', media: '(prefers-color-scheme: dark)' },
      { url: '/icon.svg', type: 'image/svg+xml' },
    ],
    apple: '/apple-icon.png',
  },
  openGraph: {
    title: 'ShopResearch - Find what you should actually buy',
    description: 'Personalized shopping research powered by Reddit and AI',
    type: 'website',
  },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
}

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <body className="font-sans antialiased min-h-screen">
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false}>
          <SessionProvider>
            <AdoptLegacy />
            {children}
          </SessionProvider>
          <Toaster
            position="bottom-right"
            toastOptions={{
              style: {
                background: 'var(--background-surface, #0F0F12)',
                border: '1px solid var(--border, rgba(255,255,255,0.1))',
                color: 'var(--foreground, #FAFAFA)',
              },
            }}
          />
          {process.env.NODE_ENV === 'production' && <Analytics />}
        </ThemeProvider>
      </body>
    </html>
  )
}

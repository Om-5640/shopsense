'use client'

import { motion, AnimatePresence } from 'framer-motion'
import {
  Star,
  ExternalLink,
  ShieldCheck,
  Zap,
  Package,
  Cpu,
  Palette,
  Tag,
  Users,
  ChevronDown,
  ChevronUp,
  ImageOff,
} from 'lucide-react'
import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { ProductPrice, LinkIntelligence, CanonicalProductData } from '@/lib/types'

interface ProductSpotlightProps {
  productName: string
  price: ProductPrice
  rank: number
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function toCurrencySymbol(currency: string) {
  if (currency === 'INR') return '₹'
  if (currency === 'USD') return '$'
  if (currency === 'GBP') return '£'
  if (currency === 'EUR') return '€'
  return currency
}

function ConfidenceBadge({ value, status }: { value: number; status: string }) {
  const pct = Math.round(value * 100)
  const isConfident = status === 'confident'

  return (
    <div
      className={cn(
        'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold',
        isConfident
          ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
          : 'bg-amber-500/15 text-amber-300 border border-amber-500/30',
      )}
    >
      <ShieldCheck className="w-3.5 h-3.5" />
      {pct}% match confidence
    </div>
  )
}

function ConsensusBar({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color =
    pct >= 85 ? 'from-emerald-500 to-teal-400' :
    pct >= 60 ? 'from-amber-500 to-orange-400' :
                'from-rose-500 to-red-400'
  const textColor =
    pct >= 85 ? 'text-emerald-400' :
    pct >= 60 ? 'text-amber-400' :
                'text-rose-400'
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span className="text-[#71717A] text-xs whitespace-nowrap">Consensus</span>
      <div className="flex-1 h-1.5 bg-white/[0.07] rounded-full overflow-hidden">
        <motion.div
          className={`h-full bg-gradient-to-r ${color} rounded-full`}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.7, ease: 'easeOut', delay: 0.3 }}
        />
      </div>
      <span className={cn('text-xs font-mono font-medium', textColor)}>{pct}%</span>
    </div>
  )
}

function SpecPill({ icon: Icon, label, value }: { icon: React.ElementType; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.07]">
      <Icon className="w-3.5 h-3.5 text-violet-400 shrink-0" />
      <div className="min-w-0">
        <div className="text-[10px] text-[#52525B] uppercase tracking-wide leading-none mb-0.5">{label}</div>
        <div className="text-xs font-medium text-[#FAFAFA] leading-none truncate">{value}</div>
      </div>
    </div>
  )
}

function StarRating({ rating, reviewCount }: { rating: number; reviewCount?: number | null }) {
  const full = Math.floor(rating)
  const half = rating - full >= 0.5

  return (
    <div className="flex items-center gap-2">
      <div className="flex items-center gap-0.5">
        {[1, 2, 3, 4, 5].map((i) => (
          <Star
            key={i}
            className={cn(
              'w-4 h-4',
              i <= full
                ? 'text-amber-400 fill-amber-400'
                : i === full + 1 && half
                ? 'text-amber-400 fill-amber-400/50'
                : 'text-white/10',
            )}
          />
        ))}
      </div>
      <span className="text-sm font-semibold text-amber-300">{rating.toFixed(1)}</span>
      {reviewCount != null && reviewCount > 0 && (
        <span className="text-xs text-[#71717A] flex items-center gap-1">
          <Users className="w-3 h-3" />
          {reviewCount.toLocaleString()} ratings
        </span>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function ProductSpotlight({ productName, price, rank }: ProductSpotlightProps) {
  const intel = price.intelligence
  const [showAlt, setShowAlt] = useState(false)

  if (!intel || intel.status !== 'confident') return null

  const sym = toCurrencySymbol(price.currency)
  const canon: CanonicalProductData | undefined = intel.canonical

  // Best retailer — use intelligence-selected URL if available, else best price
  const bestRetailer =
    price.retailers.find((r) => r.url === intel.best_url) ??
    price.retailers.find((r) => !r.is_search) ??
    price.retailers[0]

  const displayPrice =
    price.best_price?.price_inr ??
    price.best_price?.price_usd ??
    bestRetailer?.price_inr ??
    bestRetailer?.price_usd ??
    0

  const mrp = bestRetailer?.mrp_inr ?? undefined
  const discount =
    mrp && mrp > displayPrice && displayPrice > 0
      ? Math.round((1 - displayPrice / mrp) * 100)
      : null

  const imageUrl = intel.best_image ?? bestRetailer?.image_url
  const rating = intel.best_rating ?? bestRetailer?.rating
  const reviewCount = intel.best_review_count ?? bestRetailer?.review_count
  const storeUrl = intel.best_url ?? bestRetailer?.url ?? '#'
  const storeName = bestRetailer?.name ?? 'Store'

  // Build specs from canonical data
  const specs: { icon: React.ElementType; label: string; value: string }[] = []
  if (canon?.brand) specs.push({ icon: Tag, label: 'Brand', value: canon.brand })
  if (canon?.storage) specs.push({ icon: Package, label: 'Storage', value: canon.storage })
  if (canon?.ram) specs.push({ icon: Cpu, label: 'RAM', value: canon.ram })
  if (canon?.color) specs.push({ icon: Palette, label: 'Color', value: canon.color })
  if (canon?.screen_size) specs.push({ icon: Zap, label: 'Screen', value: canon.screen_size } as any)

  // Alternative retailers
  const altRetailers = price.retailers
    .filter((r) => r.url !== storeUrl && !r.is_search && (r.price_inr ?? r.price_usd))
    .slice(0, 3)

  return (
    <motion.div
      initial={{ opacity: 0, y: -16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -16 }}
      transition={{ type: 'spring', damping: 28, stiffness: 220 }}
      className="relative mb-5 rounded-2xl overflow-hidden border border-violet-500/25 bg-gradient-to-br from-violet-950/30 via-[#0C0C10] to-[#0C0C10]"
    >
      {/* Glow border effect */}
      <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-violet-500/10 via-transparent to-transparent pointer-events-none" />

      {/* Header strip */}
      <div className="flex items-center gap-2 px-5 pt-4 pb-3 border-b border-white/[0.05]">
        <div className="flex items-center gap-1.5">
          <div className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" />
          <span className="text-xs font-semibold text-violet-300 uppercase tracking-widest">
            Best Match — #{rank}
          </span>
        </div>
        <div className="ml-auto">
          <ConfidenceBadge value={intel.confidence} status={intel.status} />
        </div>
      </div>

      {/* Main content */}
      <div className="flex gap-5 p-5">
        {/* Product image */}
        <div className="shrink-0">
          <div className="w-[140px] h-[140px] rounded-2xl bg-white/[0.03] border border-white/[0.08] flex items-center justify-center overflow-hidden">
            {imageUrl ? (
              <img
                src={imageUrl}
                alt={productName}
                className="w-full h-full object-contain p-2"
                onError={(e) => {
                  const el = e.currentTarget as HTMLImageElement
                  el.style.display = 'none'
                  el.nextElementSibling?.classList.remove('hidden')
                }}
              />
            ) : null}
            <div className={cn('flex items-center justify-center w-full h-full', imageUrl ? 'hidden' : '')}>
              <ImageOff className="w-10 h-10 text-[#3F3F46]" />
            </div>
          </div>
        </div>

        {/* Info column */}
        <div className="flex-1 min-w-0 space-y-3">
          {/* Product name */}
          <h2 className="text-lg font-bold text-[#FAFAFA] leading-tight line-clamp-2">
            {intel.best_title ?? productName}
          </h2>

          {/* Rating */}
          {rating != null && rating > 0 && (
            <StarRating rating={rating} reviewCount={reviewCount} />
          )}

          {/* Specs grid */}
          {specs.length > 0 && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {specs.map((s) => (
                <SpecPill key={s.label} icon={s.icon} label={s.label} value={s.value} />
              ))}
            </div>
          )}

          {/* Consensus bar */}
          <ConsensusBar score={intel.consensus_score} />
        </div>
      </div>

      {/* Price + CTA row */}
      <div className="flex items-center gap-4 px-5 pb-5">
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 flex-wrap">
            {displayPrice > 0 ? (
              <>
                <span className="text-3xl font-bold text-[#FAFAFA] tracking-tight">
                  {sym}{displayPrice.toLocaleString()}
                </span>
                {mrp && mrp > displayPrice && (
                  <span className="text-sm text-[#52525B] line-through">
                    {sym}{mrp.toLocaleString()}
                  </span>
                )}
                {discount && discount > 0 && (
                  <Badge className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-xs">
                    {discount}% off
                  </Badge>
                )}
              </>
            ) : (
              <span className="text-sm text-[#71717A] italic">Price unavailable</span>
            )}
          </div>
          <p className="text-xs text-[#71717A] mt-0.5">on {storeName}</p>
        </div>

        <Button
          className="bg-violet-600 hover:bg-violet-500 shadow-lg shadow-violet-500/20 shrink-0"
          asChild
        >
          <a href={storeUrl} target="_blank" rel="noopener noreferrer">
            Buy on {storeName}
            <ExternalLink className="w-4 h-4 ml-1.5" />
          </a>
        </Button>
      </div>

      {/* Alternative retailers */}
      {altRetailers.length > 0 && (
        <div className="border-t border-white/[0.05]">
          <button
            onClick={() => setShowAlt(!showAlt)}
            className="w-full flex items-center justify-between px-5 py-3 text-xs text-[#71717A] hover:text-[#A1A1AA] transition-colors"
          >
            <span>Also available on {altRetailers.map((r) => r.name).join(', ')}</span>
            {showAlt ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
          <AnimatePresence>
            {showAlt && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden"
              >
                <div className="px-5 pb-4 flex flex-wrap gap-2">
                  {altRetailers.map((r) => {
                    const altPrice = r.price_inr ?? r.price_usd ?? 0
                    return (
                      <a
                        key={r.name}
                        href={r.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-2 px-3 py-2 rounded-xl bg-white/[0.03] border border-white/[0.07] hover:border-violet-500/30 transition-colors group"
                      >
                        <span className="text-xs text-[#A1A1AA] group-hover:text-[#FAFAFA] transition-colors">
                          {r.name}
                        </span>
                        {altPrice > 0 && (
                          <span className="text-xs font-semibold text-[#FAFAFA]">
                            {sym}{altPrice.toLocaleString()}
                          </span>
                        )}
                        {r.rating != null && (
                          <span className="flex items-center gap-0.5 text-xs text-amber-400">
                            <Star className="w-3 h-3 fill-amber-400" />
                            {r.rating.toFixed(1)}
                          </span>
                        )}
                        <ExternalLink className="w-3 h-3 text-[#52525B] group-hover:text-violet-400 transition-colors" />
                      </a>
                    )
                  })}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </motion.div>
  )
}

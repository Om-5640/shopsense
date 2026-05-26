'use client'

import { motion } from 'framer-motion'
import { AlertTriangle, ThumbsDown, Sparkles } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'

interface InsightsPanelProps {
  categories: Array<{ name: string; products: string[] }>
  communitySignal: Array<{ threadId: string; sentiment: 'positive' | 'neutral' | 'negative' }>
  toAvoid: Array<{ product: string; reason: string }>
  warnings: Array<{ product: string; warning: string }>
}

export function InsightsPanel({
  categories,
  communitySignal,
  toAvoid,
  warnings,
}: InsightsPanelProps) {
  const getSentimentColor = (sentiment: 'positive' | 'neutral' | 'negative') => {
    switch (sentiment) {
      case 'positive': return 'bg-emerald-500'
      case 'neutral': return 'bg-amber-500'
      case 'negative': return 'bg-rose-500'
    }
  }
  
  return (
    <div className="h-full flex flex-col">
      <h2 className="text-lg font-semibold text-[#FAFAFA] mb-4">Insights</h2>
      
      <Tabs defaultValue="categories" className="flex-1 flex flex-col">
        <TabsList className="grid w-full grid-cols-3 bg-white/[0.04] rounded-lg p-1 mb-4">
          <TabsTrigger 
            value="categories"
            className="text-xs data-[state=active]:bg-white/[0.08] data-[state=active]:text-[#FAFAFA] rounded-md"
          >
            Types
          </TabsTrigger>
          <TabsTrigger
            value="signal"
            className="text-xs data-[state=active]:bg-white/[0.08] data-[state=active]:text-[#FAFAFA] rounded-md"
          >
            Community
          </TabsTrigger>
          <TabsTrigger 
            value="avoid"
            className="text-xs data-[state=active]:bg-white/[0.08] data-[state=active]:text-[#FAFAFA] rounded-md"
          >
            Avoid
          </TabsTrigger>
        </TabsList>
        
        <TabsContent value="categories" className="flex-1 mt-0">
          <div className="space-y-4">
            {categories.map((category) => (
              <div key={category.name} className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.06]">
                <Badge className="mb-2 bg-violet-500/20 text-violet-300 border-violet-500/30">
                  {category.name}
                </Badge>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {category.products.slice(0, 3).map((product) => (
                    <span
                      key={product}
                      className="text-xs px-2 py-1 rounded-md bg-white/[0.04] text-[#A1A1AA]"
                    >
                      {product}
                    </span>
                  ))}
                  {category.products.length > 3 && (
                    <span className="text-xs px-2 py-1 text-[#71717A]">
                      +{category.products.length - 3} more
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </TabsContent>
        
        <TabsContent value="signal" className="flex-1 mt-0">
          <div className="space-y-3">
            <div className="flex items-center gap-2 mb-1">
              <Sparkles className="w-4 h-4 text-violet-400" />
              <span className="text-sm font-medium text-[#FAFAFA]">Reddit community sentiment</span>
            </div>
            <p className="text-xs text-[#71717A] mb-3">
              How Reddit users feel about each product in the results
            </p>

            {/* Summary counts */}
            {(() => {
              const pos = communitySignal.filter(s => s.sentiment === 'positive').length
              const neu = communitySignal.filter(s => s.sentiment === 'neutral').length
              const neg = communitySignal.filter(s => s.sentiment === 'negative').length
              return (
                <div className="grid grid-cols-3 gap-2 mb-4">
                  <div className="text-center p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                    <div className="text-lg font-bold text-emerald-400">{pos}</div>
                    <div className="text-[10px] text-[#71717A] mt-0.5">Highly recommended</div>
                  </div>
                  <div className="text-center p-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
                    <div className="text-lg font-bold text-amber-400">{neu}</div>
                    <div className="text-[10px] text-[#71717A] mt-0.5">Mixed opinions</div>
                  </div>
                  <div className="text-center p-2 rounded-lg bg-rose-500/10 border border-rose-500/20">
                    <div className="text-lg font-bold text-rose-400">{neg}</div>
                    <div className="text-[10px] text-[#71717A] mt-0.5">Weak signal</div>
                  </div>
                </div>
              )
            })()}

            {/* Dot grid visualization */}
            <div className="p-3 rounded-xl bg-white/[0.02] border border-white/[0.06]">
              <p className="text-[10px] text-[#52525B] mb-2 uppercase tracking-wide">
                One dot per product
              </p>
              <TooltipProvider>
                <div className="flex flex-wrap gap-1.5">
                  {communitySignal.map((signal, index) => (
                    <Tooltip key={index}>
                      <TooltipTrigger asChild>
                        <motion.div
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                          transition={{ delay: index * 0.04 }}
                          className={`w-3.5 h-3.5 rounded-full cursor-default ${getSentimentColor(signal.sentiment)}`}
                        />
                      </TooltipTrigger>
                      <TooltipContent side="top">
                        <p className="text-xs capitalize">
                          {signal.sentiment === 'positive' ? 'Highly recommended on Reddit'
                            : signal.sentiment === 'negative' ? 'Weak or negative signal'
                            : 'Mixed community opinions'}
                        </p>
                      </TooltipContent>
                    </Tooltip>
                  ))}
                </div>
              </TooltipProvider>
            </div>
          </div>
        </TabsContent>
        
        <TabsContent value="avoid" className="flex-1 mt-0">
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm text-rose-400 mb-2">
              <ThumbsDown className="w-4 h-4" />
              <span className="font-medium">Products to avoid</span>
            </div>
            
            {toAvoid.map((item) => (
              <div
                key={item.product}
                className="p-3 rounded-xl bg-rose-500/5 border border-rose-500/20"
              >
                <p className="text-sm font-medium text-[#FAFAFA] mb-1">{item.product}</p>
                <p className="text-xs text-[#A1A1AA]">{item.reason}</p>
              </div>
            ))}
            
            {warnings.length > 0 && (
              <>
                <div className="flex items-center gap-2 text-sm text-amber-400 mt-4 mb-2">
                  <AlertTriangle className="w-4 h-4" />
                  <span className="font-medium">Split opinions</span>
                </div>
                
                {warnings.map((item) => (
                  <div
                    key={item.product}
                    className="p-3 rounded-xl bg-amber-500/5 border border-amber-500/20"
                  >
                    <p className="text-sm font-medium text-[#FAFAFA] mb-1">{item.product}</p>
                    <p className="text-xs text-[#A1A1AA]">{item.warning}</p>
                  </div>
                ))}
              </>
            )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}

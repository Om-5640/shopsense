"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Star,
  ExternalLink,
  Plus,
  Minus,
  Heart,
  Share2,
  MessageSquare,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  CheckCircle2,
  Quote,
  ThumbsUp,
  ThumbsDown,
  BarChart3,
  Shield,
  Zap,
  Clock,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

interface Product {
  id: string
  name: string
  brand: string
  price: number
  image: string
  rating: number
  reviewCount: number
  pros: string[]
  cons: string[]
  scores: Record<string, number>
  rank: number
  affiliate: string
  redditMentions: number
  sentimentScore: number
  priceHistory: { date: string; price: number }[]
}

// Mock product data (in real app this would come from the store or API)
const mockProduct: Product = {
  id: "sony-wh1000xm5",
  name: "Sony WH-1000XM5",
  brand: "Sony",
  price: 349,
  image: "https://images.unsplash.com/photo-1618366712010-f4ae9c647dcb?w=600&h=600&fit=crop",
  rating: 4.8,
  reviewCount: 12847,
  pros: [
    "Industry-leading noise cancellation",
    "Exceptional sound quality with LDAC support",
    "30-hour battery life",
    "Speak-to-chat feature works flawlessly",
    "Lightweight and comfortable for long sessions",
    "Multi-point connection for 2 devices",
  ],
  cons: [
    "No IP rating for water resistance",
    "Cannot fold flat for storage",
    "Touch controls can be finicky",
    "Premium price point",
  ],
  scores: {
    "Sound Quality": 95,
    "Noise Cancellation": 98,
    "Comfort": 92,
    "Battery Life": 94,
    "Build Quality": 88,
    "Value": 82,
  },
  rank: 1,
  affiliate: "https://amazon.com",
  redditMentions: 2847,
  sentimentScore: 0.92,
  priceHistory: [
    { date: "2024-01", price: 399 },
    { date: "2024-02", price: 379 },
    { date: "2024-03", price: 349 },
    { date: "2024-04", price: 349 },
    { date: "2024-05", price: 329 },
    { date: "2024-06", price: 349 },
  ],
};

const mockReviews = [
  {
    id: 1,
    source: "r/headphones",
    author: "audiophile_dave",
    content: "After 6 months of daily use, these are still the best ANC headphones I've ever owned. The sound quality is phenomenal, especially with LDAC enabled on my Pixel.",
    upvotes: 847,
    date: "2 weeks ago",
    sentiment: "positive",
  },
  {
    id: 2,
    source: "r/WirelessHeadphones",
    author: "tech_reviewer_mike",
    content: "Compared directly with the Bose QC Ultra and Apple AirPods Max. Sony wins on ANC and battery, Bose on call quality, Apple on build. Overall, Sony is my pick.",
    upvotes: 623,
    date: "1 month ago",
    sentiment: "positive",
  },
  {
    id: 3,
    source: "r/audiophile",
    author: "sound_purist",
    content: "For wireless, these are impressive. But let's be real - they don't compare to even mid-range wired cans. Good for travel, not for critical listening.",
    upvotes: 412,
    date: "3 weeks ago",
    sentiment: "neutral",
  },
  {
    id: 4,
    source: "r/headphones",
    author: "daily_commuter",
    content: "The new folding design is worse than XM4. Can't throw these in a bag as easily. Sound is better though.",
    upvotes: 234,
    date: "2 months ago",
    sentiment: "mixed",
  },
];

const specifications = [
  { label: "Driver Size", value: "30mm" },
  { label: "Frequency Response", value: "4Hz - 40kHz" },
  { label: "Impedance", value: "48 ohms" },
  { label: "Sensitivity", value: "102 dB" },
  { label: "Battery Life", value: "30 hours (ANC on)" },
  { label: "Charging Time", value: "3.5 hours (full), 3 min (3 hours playback)" },
  { label: "Weight", value: "250g" },
  { label: "Bluetooth Version", value: "5.2" },
  { label: "Codecs", value: "SBC, AAC, LDAC" },
  { label: "Multipoint", value: "Yes (2 devices)" },
];

export default function ProductDetailPage() {
  const params = useParams();
  const router = useRouter();
  const [activeTab, setActiveTab] = useState("overview");
  const [liked, setLiked] = useState(false);
  const [isInCompare, setIsInCompare] = useState(false);

  const product = mockProduct; // In real app, fetch based on params.id
  void params; // used via router for the route param

  const overallScore = Math.round(
    Object.values(product.scores).reduce((a, b) => a + b, 0) / Object.values(product.scores).length
  );

  return (
    <div className="min-h-screen bg-[#0A0A0C] text-[#FAFAFA]">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-white/[0.06] bg-black/40 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="icon" onClick={() => router.back()}>
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <h1 className="font-semibold text-[#FAFAFA]">{product.name}</h1>
              <p className="text-sm text-[#71717A]">{product.brand}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="icon" onClick={() => setLiked(!liked)}>
              <Heart className={cn("h-5 w-5", liked && "fill-red-500 text-red-500")} />
            </Button>
            <Button variant="ghost" size="icon">
              <Share2 className="h-5 w-5" />
            </Button>
            <Button
              variant={isInCompare ? "secondary" : "outline"}
              onClick={() => !isInCompare && setIsInCompare(true)}
              disabled={isInCompare}
            >
              {isInCompare ? "In Compare" : "Add to Compare"}
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8">
        {/* Hero Section */}
        <div className="mb-12 grid gap-8 lg:grid-cols-2">
          {/* Product Image */}
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            className="relative aspect-square overflow-hidden rounded-2xl bg-[#18181B]"
          >
            <img
              src={product.image}
              alt={product.name}
              className="h-full w-full object-cover"
            />
            <div className="absolute left-4 top-4">
              <Badge className="bg-primary text-primary-foreground">
                #{product.rank} Ranked
              </Badge>
            </div>
          </motion.div>

          {/* Product Info */}
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            className="flex flex-col"
          >
            <div className="mb-6">
              <div className="mb-2 flex items-center gap-3">
                <div className="flex items-center gap-1">
                  <Star className="h-5 w-5 fill-yellow-500 text-yellow-500" />
                  <span className="font-semibold">{product.rating}</span>
                </div>
                <span className="text-sm text-muted-foreground">
                  ({product.reviewCount.toLocaleString()} reviews)
                </span>
                <Badge variant="outline" className="gap-1">
                  <MessageSquare className="h-3 w-3" />
                  {product.redditMentions.toLocaleString()} Reddit mentions
                </Badge>
              </div>
              <h2 className="mb-2 text-4xl font-bold">{product.name}</h2>
              <p className="text-lg text-muted-foreground">by {product.brand}</p>
            </div>

            {/* Overall Score */}
            <div className="mb-6 rounded-xl border border-white/[0.06] bg-[#18181B] p-6">
              <div className="mb-4 flex items-center justify-between">
                <span className="text-sm font-medium text-[#71717A]">ShopResearch Score</span>
                <div className="flex items-center gap-2">
                  <div className="text-4xl font-bold text-primary">{overallScore}</div>
                  <span className="text-sm text-[#71717A]">/100</span>
                </div>
              </div>
              <Progress value={overallScore} className="h-2" />
              <p className="mt-3 text-sm text-[#71717A]">
                Based on {product.redditMentions.toLocaleString()} community discussions and expert analysis
              </p>
            </div>

            {/* Price */}
            <div className="mb-6">
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-bold">${product.price}</span>
                {product.priceHistory && product.priceHistory[0].price > product.price && (
                  <Badge variant="secondary" className="gap-1 text-green-600">
                    <TrendingDown className="h-3 w-3" />
                    ${product.priceHistory[0].price - product.price} below avg
                  </Badge>
                )}
              </div>
            </div>

            {/* CTA Buttons */}
            <div className="flex gap-3">
              <Button size="lg" className="flex-1 gap-2" asChild>
                <a href={product.affiliate} target="_blank" rel="noopener noreferrer">
                  View Best Price
                  <ExternalLink className="h-4 w-4" />
                </a>
              </Button>
              <Button size="lg" variant="outline" className="gap-2">
                <BarChart3 className="h-4 w-4" />
                Price History
              </Button>
            </div>

            {/* Trust Indicators */}
            <div className="mt-6 flex items-center gap-6 text-sm text-[#71717A]">
              <div className="flex items-center gap-2">
                <Shield className="h-4 w-4 text-green-500" />
                <span>Verified Reviews</span>
              </div>
              <div className="flex items-center gap-2">
                <Zap className="h-4 w-4 text-yellow-500" />
                <span>AI-Analyzed</span>
              </div>
              <div className="flex items-center gap-2">
                <Clock className="h-4 w-4 text-blue-500" />
                <span>Updated 2h ago</span>
              </div>
            </div>
          </motion.div>
        </div>

        {/* Tabs Section */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-8">
          <TabsList className="grid w-full grid-cols-4 lg:w-auto lg:grid-cols-none lg:flex">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="reviews">Community Reviews</TabsTrigger>
            <TabsTrigger value="specs">Specifications</TabsTrigger>
            <TabsTrigger value="alternatives">Alternatives</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-8">
            {/* Score Breakdown */}
            <div className="rounded-xl border border-white/[0.06] bg-[#18181B] p-6">
              <h3 className="mb-6 text-lg font-semibold text-[#FAFAFA]">Score Breakdown</h3>
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {Object.entries(product.scores).map(([category, score]) => (
                  <div key={category} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-[#A1A1AA]">{category}</span>
                      <span className="text-sm font-semibold text-[#FAFAFA]">{score}/100</span>
                    </div>
                    <Progress value={score} className="h-2" />
                  </div>
                ))}
              </div>
            </div>

            {/* Pros & Cons */}
            <div className="grid gap-6 md:grid-cols-2">
              <div className="rounded-xl border border-green-500/20 bg-green-500/5 p-6">
                <h3 className="mb-4 flex items-center gap-2 text-lg font-semibold text-green-600">
                  <CheckCircle2 className="h-5 w-5" />
                  What People Love
                </h3>
                <ul className="space-y-3">
                  {product.pros.map((pro, i) => (
                    <motion.li
                      key={i}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.1 }}
                      className="flex items-start gap-2 text-sm"
                    >
                      <Plus className="mt-0.5 h-4 w-4 shrink-0 text-green-500" />
                      <span>{pro}</span>
                    </motion.li>
                  ))}
                </ul>
              </div>

              <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-6">
                <h3 className="mb-4 flex items-center gap-2 text-lg font-semibold text-red-600">
                  <AlertTriangle className="h-5 w-5" />
                  Common Concerns
                </h3>
                <ul className="space-y-3">
                  {product.cons.map((con, i) => (
                    <motion.li
                      key={i}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.1 }}
                      className="flex items-start gap-2 text-sm"
                    >
                      <Minus className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
                      <span>{con}</span>
                    </motion.li>
                  ))}
                </ul>
              </div>
            </div>

            {/* Sentiment Analysis */}
            <div className="rounded-xl border border-white/[0.06] bg-[#18181B] p-6">
              <h3 className="mb-4 text-lg font-semibold text-[#FAFAFA]">Community Sentiment</h3>
              <div className="flex items-center gap-8">
                <div className="flex items-center gap-3">
                  <div className="flex h-12 w-12 items-center justify-center rounded-full bg-green-500/10">
                    <ThumbsUp className="h-6 w-6 text-green-500" />
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-[#FAFAFA]">{Math.round(product.sentimentScore * 100)}%</div>
                    <div className="text-sm text-[#71717A]">Positive</div>
                  </div>
                </div>
                <div className="h-12 w-px bg-[#27272A]" />
                <div className="flex-1">
                  <div className="mb-2 flex justify-between text-sm text-[#A1A1AA]">
                    <span>Positive</span>
                    <span>Negative</span>
                  </div>
                  <div className="h-3 overflow-hidden rounded-full bg-red-500/20">
                    <div
                      className="h-full bg-green-500 transition-all"
                      style={{ width: `${product.sentimentScore * 100}%` }}
                    />
                  </div>
                </div>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="reviews" className="space-y-4">
            {mockReviews.map((review, i) => (
              <motion.div
                key={review.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.1 }}
                className="rounded-xl border border-white/[0.06] bg-[#18181B] p-6"
              >
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Badge variant="outline">{review.source}</Badge>
                    <span className="font-medium text-[#FAFAFA]">u/{review.author}</span>
                    <span className="text-sm text-[#71717A]">{review.date}</span>
                  </div>
                  <div className="flex items-center gap-1 text-sm text-[#71717A]">
                    <ThumbsUp className="h-4 w-4" />
                    {review.upvotes}
                  </div>
                </div>
                <div className="flex gap-3">
                  <Quote className="mt-1 h-5 w-5 shrink-0 text-[#52525B]" />
                  <p className="text-[#A1A1AA]">{review.content}</p>
                </div>
              </motion.div>
            ))}
          </TabsContent>

          <TabsContent value="specs">
            <div className="rounded-xl border border-white/[0.06] bg-[#18181B] p-6">
              <h3 className="mb-6 text-lg font-semibold text-[#FAFAFA]">Technical Specifications</h3>
              <div className="grid gap-4 md:grid-cols-2">
                {specifications.map((spec, i) => (
                  <div
                    key={spec.label}
                    className="flex items-center justify-between border-b border-[#27272A] py-3 last:border-0"
                  >
                    <span className="text-[#71717A]">{spec.label}</span>
                    <span className="font-medium text-[#FAFAFA]">{spec.value}</span>
                  </div>
                ))}
              </div>
            </div>
          </TabsContent>

          <TabsContent value="alternatives">
            <div className="rounded-xl border border-white/[0.06] bg-[#18181B] p-6">
              <h3 className="mb-6 text-lg font-semibold text-[#FAFAFA]">Similar Products</h3>
              <p className="text-[#71717A]">
                Run a new research to discover alternatives tailored to your specific needs.
              </p>
              <Button className="mt-4" asChild>
                <Link href="/">Start New Research</Link>
              </Button>
            </div>
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}

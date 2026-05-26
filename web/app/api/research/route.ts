import { NextResponse } from "next/server";

// Simulated research API endpoint
export async function POST(request: Request) {
  const body = await request.json();
  const { query, preferences } = body;

  // In a real app, this would trigger the AI research pipeline
  // For now, we return a mock research ID
  const researchId = `research-${Date.now()}`;

  return NextResponse.json({
    id: researchId,
    status: "started",
    query,
    preferences,
    estimatedTime: "2-3 minutes",
  });
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const id = searchParams.get("id");

  if (!id) {
    return NextResponse.json({ error: "Research ID required" }, { status: 400 });
  }

  // Mock research status
  return NextResponse.json({
    id,
    status: "completed",
    progress: 100,
    steps: [
      { name: "Understanding query", status: "completed" },
      { name: "Fetching Reddit discussions", status: "completed" },
      { name: "Analyzing sentiment", status: "completed" },
      { name: "Ranking products", status: "completed" },
    ],
  });
}

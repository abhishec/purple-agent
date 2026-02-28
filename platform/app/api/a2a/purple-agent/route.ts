import { NextRequest, NextResponse } from "next/server";
import { BenchmarkSolver } from "@/platform/lib/a2a/benchmark-solver";
import { z } from "zod";

const solver = new BenchmarkSolver();

// ─── Health check ─────────────────────────────────────────────────────────────

export async function GET() {
  return NextResponse.json({
    agent: "purple-agent",
    version: "0.1.0",
    status: "ready",
    capabilities: ["policy_enforcement", "memory_compression", "structured_output"],
    timestamp: new Date().toISOString(),
  });
}

// ─── A2A task handler ─────────────────────────────────────────────────────────

export async function POST(request: NextRequest) {
  let body: unknown;

  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: "Invalid JSON in request body" },
      { status: 400 }
    );
  }

  // Validate the minimum required fields
  const MinimalSchema = z.object({
    task_id: z.string().min(1),
    task: z.string().min(1),
  });

  const minimal = MinimalSchema.safeParse(body);
  if (!minimal.success) {
    return NextResponse.json(
      {
        error: "Missing required fields",
        details: minimal.error.flatten(),
      },
      { status: 422 }
    );
  }

  try {
    const result = await solver.solve(body);

    return NextResponse.json(
      {
        task_id: result.task_id,
        answers: result.answers,
        metadata: {
          policy_compliant: result.policy_compliant,
          policy_violations: result.policy_violations,
          applied_rules: result.applied_rules,
          memory_compressed: result.memory_summary !== null,
          memory_summary: result.memory_summary,
        },
      },
      { status: 200 }
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";

    // Validation errors → 422
    if (message.includes("ZodError") || err instanceof z.ZodError) {
      return NextResponse.json(
        { error: "Invalid task payload", details: message },
        { status: 422 }
      );
    }

    // LLM / upstream errors → 502
    if (message.includes("Anthropic") || message.includes("rate limit")) {
      return NextResponse.json(
        { error: "Upstream LLM error", details: message },
        { status: 502 }
      );
    }

    return NextResponse.json(
      { error: "Internal solver error", details: message },
      { status: 500 }
    );
  }
}

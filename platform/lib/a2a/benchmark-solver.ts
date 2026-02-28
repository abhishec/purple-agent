import Anthropic from "@anthropic-ai/sdk";
import { z } from "zod";

// ─── Schemas ─────────────────────────────────────────────────────────────────

export const PolicyDocSchema = z.object({
  rules: z.array(
    z.object({
      id: z.string(),
      description: z.string(),
      type: z.enum(["allow", "deny", "require"]),
      pattern: z.string().optional(),
      keywords: z.array(z.string()).optional(),
    })
  ),
  default_action: z.enum(["allow", "deny"]).default("allow"),
});

export const ConversationTurnSchema = z.object({
  role: z.enum(["user", "assistant"]),
  content: z.string(),
  turn_id: z.number().optional(),
  timestamp: z.string().optional(),
});

export const BenchmarkTaskSchema = z.object({
  task_id: z.string(),
  task: z.string(),
  policy_doc: PolicyDocSchema.optional(),
  history: z.array(ConversationTurnSchema).optional().default([]),
  expected_format: z.enum(["list", "single", "json"]).optional().default("list"),
  context: z.string().optional(),
});

export type PolicyDoc = z.infer<typeof PolicyDocSchema>;
export type ConversationTurn = z.infer<typeof ConversationTurnSchema>;
export type BenchmarkTask = z.infer<typeof BenchmarkTaskSchema>;

// ─── Policy Evaluator ────────────────────────────────────────────────────────

export class PolicyEvaluator {
  evaluate(task: string, policy: PolicyDoc): { compliant: boolean; violations: string[]; applied_rules: string[] } {
    const violations: string[] = [];
    const applied_rules: string[] = [];
    const taskLower = task.toLowerCase();

    for (const rule of policy.rules) {
      const keywords = rule.keywords ?? [];
      const patternMatches = rule.pattern
        ? new RegExp(rule.pattern, "i").test(task)
        : false;
      const keywordMatches = keywords.some((kw) =>
        taskLower.includes(kw.toLowerCase())
      );
      const matched = patternMatches || keywordMatches;

      if (matched) {
        applied_rules.push(rule.id);
        if (rule.type === "deny") {
          violations.push(`Rule ${rule.id}: ${rule.description}`);
        }
      }

      if (rule.type === "require" && !matched) {
        violations.push(`Rule ${rule.id} (required but missing): ${rule.description}`);
      }
    }

    const compliant =
      violations.length === 0
        ? true
        : policy.default_action === "allow"
        ? violations.every((v) => !v.includes("deny"))
        : false;

    return { compliant, violations, applied_rules };
  }
}

// ─── Memory Compressor ───────────────────────────────────────────────────────

export class MemoryCompressor {
  private readonly MAX_TURNS = 10;
  private readonly SUMMARY_THRESHOLD = 6;

  compress(history: ConversationTurn[]): { compressed: ConversationTurn[]; summary: string | null } {
    if (history.length <= this.SUMMARY_THRESHOLD) {
      return { compressed: history, summary: null };
    }

    const toSummarize = history.slice(0, history.length - this.MAX_TURNS + 2);
    const recent = history.slice(history.length - this.MAX_TURNS + 2);

    const keyPoints = toSummarize
      .filter((t) => t.role === "assistant")
      .map((t) => {
        const content = t.content.trim();
        return content.length > 120 ? content.slice(0, 120) + "…" : content;
      })
      .slice(-3);

    const summary = keyPoints.length > 0
      ? `[Prior context summary: ${keyPoints.join(" | ")}]`
      : null;

    const compressed: ConversationTurn[] = summary
      ? [{ role: "assistant", content: summary }, ...recent]
      : recent;

    return { compressed, summary };
  }

  toMessages(turns: ConversationTurn[]): Array<{ role: "user" | "assistant"; content: string }> {
    return turns.map((t) => ({ role: t.role, content: t.content }));
  }
}

// ─── Output Formatter ────────────────────────────────────────────────────────

export class OutputFormatter {
  parseList(raw: string): string[] {
    // Try JSON array first
    const jsonMatch = raw.match(/\[[\s\S]*?\]/);
    if (jsonMatch) {
      try {
        const parsed = JSON.parse(jsonMatch[0]);
        if (Array.isArray(parsed)) {
          return parsed
            .map((item) => String(item).trim())
            .filter(Boolean)
            .sort();
        }
      } catch {}
    }

    // Try numbered/bulleted list
    const lines = raw.split(/\n/).map((l) => l.trim());
    const listItems = lines
      .map((l) => l.replace(/^[-*•]|\d+[.)]\s*/, "").trim())
      .filter((l) => l.length > 0 && l.length < 200);

    if (listItems.length > 1) {
      return listItems.sort();
    }

    // Fallback: split by comma or semicolon
    const delimited = raw
      .split(/[,;]/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0 && s.length < 200);

    if (delimited.length > 1) {
      return delimited.sort();
    }

    return [raw.trim()];
  }

  formatResponse(answers: string[], format: BenchmarkTask["expected_format"]): unknown {
    const sorted = [...answers].sort();
    switch (format) {
      case "list":
        return sorted;
      case "single":
        return sorted[0] ?? "";
      case "json":
        return { answers: sorted };
      default:
        return sorted;
    }
  }
}

// ─── Benchmark Solver ────────────────────────────────────────────────────────

export interface SolverResult {
  task_id: string;
  answers: unknown;
  policy_compliant: boolean;
  policy_violations: string[];
  applied_rules: string[];
  memory_summary: string | null;
  raw_response: string;
}

export class BenchmarkSolver {
  private client: Anthropic;
  private policyEvaluator: PolicyEvaluator;
  private memoryCompressor: MemoryCompressor;
  private outputFormatter: OutputFormatter;

  constructor() {
    this.client = new Anthropic();
    this.policyEvaluator = new PolicyEvaluator();
    this.memoryCompressor = new MemoryCompressor();
    this.outputFormatter = new OutputFormatter();
  }

  async solve(input: unknown): Promise<SolverResult> {
    const task = BenchmarkTaskSchema.parse(input);

    // 1. Policy check — deterministic, no LLM
    const policyResult = task.policy_doc
      ? this.policyEvaluator.evaluate(task.task, task.policy_doc)
      : { compliant: true, violations: [], applied_rules: [] };

    // 2. Compress memory
    const { compressed, summary } = this.memoryCompressor.compress(task.history);
    const messages = this.memoryCompressor.toMessages(compressed);

    // 3. Build system prompt with policy constraints
    const policyInstructions = task.policy_doc
      ? this.buildPolicyInstructions(task.policy_doc, policyResult)
      : "";

    const systemPrompt = [
      "You are a precise benchmark-solving agent.",
      "Return answers as a JSON array of strings: [\"Answer1\", \"Answer2\"].",
      "Sort the array alphabetically. No prose, no explanation — only the JSON array.",
      policyInstructions,
      task.context ? `\nContext:\n${task.context}` : "",
    ]
      .filter(Boolean)
      .join("\n");

    // 4. Call LLM
    const response = await this.client.messages.create({
      model: "claude-sonnet-4-6",
      max_tokens: 1024,
      system: systemPrompt,
      messages: [
        ...messages,
        { role: "user", content: task.task },
      ],
    });

    const rawResponse =
      response.content[0].type === "text" ? response.content[0].text : "";

    // 5. Parse + format output
    const parsed = this.outputFormatter.parseList(rawResponse);
    const answers = this.outputFormatter.formatResponse(parsed, task.expected_format);

    return {
      task_id: task.task_id,
      answers,
      policy_compliant: policyResult.compliant,
      policy_violations: policyResult.violations,
      applied_rules: policyResult.applied_rules,
      memory_summary: summary,
      raw_response: rawResponse,
    };
  }

  private buildPolicyInstructions(policy: PolicyDoc, evaluation: ReturnType<PolicyEvaluator["evaluate"]>): string {
    if (evaluation.violations.length === 0) return "";
    return [
      "\nPOLICY CONSTRAINTS (enforced deterministically — do not override):",
      ...evaluation.violations.map((v) => `  - ${v}`),
      "You MUST respect these constraints in your response.",
    ].join("\n");
  }
}

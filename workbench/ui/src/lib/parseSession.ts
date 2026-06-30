export interface ParsedSession {
  session_id: string | null;
  current_node: string | null;
  task_type: string | null;
  risk_level: string | null;
  escalation_tier: string | null;
  final_decision: string | null;
  current_task: string | null;
  revision_count: number | null;
  transition_blocked: boolean;
  human_questions: string[];
  repair_conditions: string[];
  message_text: string;
  summary_text: string;
}

export function parseSessionOutput(stdout: string): ParsedSession {
  const result: ParsedSession = {
    session_id: null,
    current_node: null,
    task_type: null,
    risk_level: null,
    escalation_tier: null,
    final_decision: null,
    current_task: null,
    revision_count: null,
    transition_blocked: false,
    human_questions: [],
    repair_conditions: [],
    message_text: "",
    summary_text: "",
  };

  const lines = stdout.split("\n");
  const narrativeLines: string[] = [];
  let inQuestions = false;
  let inRepairs = false;
  let inSummary = false;

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith("── State Summary")) {
      inSummary = true;
      inQuestions = false;
      inRepairs = false;
      continue;
    }
    if (trimmed.startsWith("──────")) {
      inSummary = false;
      continue;
    }

    if (trimmed === "Human questions:") {
      inQuestions = true;
      inRepairs = false;
      continue;
    }

    if (trimmed.startsWith("WARNING: Transition blocked")) {
      result.transition_blocked = true;
      inQuestions = false;
      inRepairs = true;
      continue;
    }

    if (inQuestions && trimmed.startsWith("- ")) {
      result.human_questions.push(trimmed.slice(2));
      continue;
    }
    if (inQuestions && !trimmed.startsWith("- ") && trimmed !== "") {
      inQuestions = false;
    }

    if (inRepairs && trimmed.startsWith("- ")) {
      result.repair_conditions.push(trimmed.slice(2));
      continue;
    }
    if (inRepairs && !trimmed.startsWith("- ") && trimmed !== "") {
      inRepairs = false;
    }

    if (inSummary) {
      const match = trimmed.match(/^(\w+):\s*(.+)/);
      if (match) {
        const [, key, val] = match;
        switch (key) {
          case "session_id": result.session_id = val; break;
          case "task_type": result.task_type = val; break;
          case "risk_level": result.risk_level = val; break;
          case "escalation_tier": result.escalation_tier = val; break;
          case "current_node": result.current_node = val; break;
          case "revision_count": result.revision_count = parseInt(val, 10) || null; break;
          case "current_task_filename": result.current_task = val; break;
          case "final_decision": result.final_decision = val; break;
        }
      }
      continue;
    }

    if (trimmed === "" || trimmed.startsWith("──")) {
      if (trimmed === "" && narrativeLines.length > 0 && narrativeLines[narrativeLines.length - 1] !== "") {
        narrativeLines.push("");
      }
      continue;
    }

    const sessionMatch = trimmed.match(/^Session:\s*(.+)/);
    if (sessionMatch) {
      result.session_id = sessionMatch[1];
      continue;
    }
    const decisionMatch = trimmed.match(/^Decision:\s*(.+)/);
    if (decisionMatch) {
      result.final_decision = decisionMatch[1];
      continue;
    }
    const taskMatch = trimmed.match(/^Task:\s*(.+)/);
    if (taskMatch) {
      result.current_task = taskMatch[1];
      continue;
    }

    if (trimmed.startsWith("Invoking workbench graph")) {
      continue;
    }

    if (isTechnicalLine(trimmed)) {
      continue;
    }

    if (inQuestions || inRepairs) {
      continue;
    }

    narrativeLines.push(line.trimEnd());
  }

  result.message_text = compactText(narrativeLines.join("\n"));
  result.summary_text = buildSummaryText(result);
  return result;
}

function compactText(text: string): string {
  return text
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]+\n/g, "\n")
    .trim();
}

function buildSummaryText(result: ParsedSession): string {
  const parts: string[] = [];

  if (result.current_task) {
    parts.push(`Task ${result.current_task}`);
  }
  if (result.current_node) {
    parts.push(`at ${result.current_node}`);
  }
  if (result.final_decision) {
    parts.push(`decision ${result.final_decision}`);
  }
  if (result.transition_blocked) {
    parts.push("transition blocked");
  }

  if (parts.length === 0 && result.session_id) {
    return `Session ${result.session_id}`;
  }

  if (parts.length === 0) {
    return "";
  }

  return parts.join(", ");
}

function isTechnicalLine(line: string): boolean {
  return (
    line.startsWith("Traceback (most recent call last):") ||
    line.startsWith("File ") ||
    /^[A-Z][A-Za-z0-9_]*Error:/.test(line) ||
    line.startsWith("RuntimeError:") ||
    line.startsWith("ValueError:") ||
    line.startsWith("TypeError:") ||
    line.startsWith("AssertionError:") ||
    line.startsWith("WARNING:") ||
    line.startsWith("[") ||
    line.startsWith("▶") ||
    line.startsWith("• [") ||
    line.startsWith("^")
  );
}

import type { CommandResult } from "../types";
import { parseSessionOutput } from "../lib/parseSession";
import { humanizeLabel, speakerColor } from "../lib/speakers";

interface Props {
  result: CommandResult | null;
  running: boolean;
}

interface ThreadEntry {
  role: "system" | "human" | "assistant" | "decision";
  speaker?: string;
  content: string;
}

function buildThread(result: CommandResult): ThreadEntry[] {
  const entries: ThreadEntry[] = [];
  const parsed = parseSessionOutput(result.stdout);

  const body = parsed.message_text || parsed.summary_text || result.stderr || "";

  if (body) {
    entries.push({
      role: "assistant",
      speaker: parsed.current_node ? humanizeLabel(parsed.current_node) : "Workbench",
      content: body,
    });
  } else if (parsed.session_id) {
    entries.push({
      role: "system",
      content: `Session ${parsed.session_id} did not return renderable text.`,
    });
  }

  if (parsed.session_id || parsed.current_task || parsed.current_node || parsed.final_decision) {
    const meta = [
      parsed.session_id && `Session ${parsed.session_id}`,
      parsed.current_task && `Task ${parsed.current_task}`,
      parsed.current_node && `Node ${parsed.current_node}`,
      parsed.final_decision && `Decision ${parsed.final_decision}`,
    ].filter(Boolean);

    if (meta.length > 0) {
      entries.push({ role: "system", content: meta.join(" • ") });
    }
  }

  if (parsed.human_questions.length > 0) {
    entries.push({
      role: "assistant",
      speaker: "Questions",
      content: parsed.human_questions.map((q) => `• ${q}`).join("\n"),
    });
  }

  if (parsed.transition_blocked || parsed.repair_conditions.length > 0) {
    const repairs = parsed.repair_conditions.length > 0
      ? parsed.repair_conditions.map((r) => `• ${r}`).join("\n")
      : "Transition blocked";
    entries.push({ role: "system", content: repairs });
  }

  return entries;
}

export function SessionThread({ result, running }: Props) {
  if (running) {
    return (
      <div className="session-thread">
        <div className="thread-entry thread-entry--system">
          <span className="thread-role">System</span>
          <span className="thread-body">Running...</span>
        </div>
      </div>
    );
  }

  if (!result) return null;

  const entries = buildThread(result);

  if (entries.length === 0 && result.stdout) {
    return (
      <div className="session-thread">
        <div className="thread-entry thread-entry--system">
          <span className="thread-role">Output</span>
          <pre className="thread-pre">{result.stdout}</pre>
        </div>
      </div>
    );
  }

  return (
    <div className="session-thread">
      {entries.map((e, i) => (
        <div key={i} className={`thread-entry thread-entry--${e.role}`}>
          {e.speaker && (
            <span className="thread-speaker" style={{ color: speakerColor(e.speaker) }}>
              {e.speaker}
            </span>
          )}
          <div className="thread-body">{e.content}</div>
        </div>
      ))}
      {result.stdout && (
        <details className="thread-raw">
          <summary>Raw output</summary>
          <pre className="thread-pre">{result.stdout}</pre>
        </details>
      )}
    </div>
  );
}

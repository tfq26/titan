import type { CommandResult } from "../types";
import { parseSessionOutput } from "../lib/parseSession";

interface Props {
  sessionId: string | null;
  lastResult: CommandResult | null;
}

export function SessionStatus({ sessionId, lastResult }: Props) {
  const parsed = lastResult?.stdout
    ? parseSessionOutput(lastResult.stdout)
    : null;

  const displayId = parsed?.session_id ?? sessionId;

  return (
    <div className="panel session-status">
      <h3 className="panel__title">Session</h3>
      {!displayId && !lastResult ? (
        <div className="panel--empty">No active session</div>
      ) : (
        <div className="session-fields">
          {renderField("Session ID", displayId)}
          {renderField("Current Node", parsed?.current_node)}
          {renderField("Task Type", parsed?.task_type)}
          {renderField("Risk Level", parsed?.risk_level)}
          {renderField("Escalation", parsed?.escalation_tier)}
          {renderField("Task", parsed?.current_task)}
          {renderField("Revision", parsed?.revision_count)}
          {renderField("Decision", parsed?.final_decision)}
          {parsed?.transition_blocked && (
            <div className="field field--warn">
              <span className="field__label">Blocked</span>
              <span className="field__value">Transition blocked</span>
            </div>
          )}
          {parsed?.repair_conditions && parsed.repair_conditions.length > 0 && (
            <div className="field field--warn">
              <span className="field__label">Repairs</span>
              <ul className="question-list">
                {parsed.repair_conditions.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </div>
          )}
          {parsed?.human_questions && parsed.human_questions.length > 0 && (
            <div className="field">
              <span className="field__label">Questions</span>
              <ul className="question-list">
                {parsed.human_questions.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </div>
          )}
          {lastResult?.stdout && (
            <details className="session-raw">
              <summary>Raw output</summary>
              <pre className="content-pre">{lastResult.stdout}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function renderField(label: string, value: unknown) {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div className="field">
      <span className="field__label">{label}</span>
      <span className="field__value">{String(value)}</span>
    </div>
  );
}

import { useState } from "react";
import type { CommandResult } from "../types";
import { resumeWithResponse } from "../bridge/cli";

interface Props {
  projectId: string | null;
  sessionId: string | null;
  pendingQuestions: string[];
}

export function ApprovalPanel({ projectId, sessionId, pendingQuestions }: Props) {
  const [response, setResponse] = useState("");
  const [result, setResult] = useState<CommandResult | null>(null);
  const [running, setRunning] = useState(false);

  const handleSubmit = async () => {
    if (!projectId || !sessionId || !response.trim()) return;
    setRunning(true);
    try {
      const r = await resumeWithResponse(projectId, sessionId, response.trim());
      setResult(r);
      setResponse("");
    } catch (e) {
      setResult({ stdout: "", stderr: String(e), exit_code: 1 });
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="panel approval-panel">
      <h3 className="panel__title">Approval / Checkpoint</h3>

      {pendingQuestions.length > 0 ? (
        <div className="approval-questions">
          <div className="approval-label">Pending questions:</div>
          <ul className="question-list">
            {pendingQuestions.map((q, i) => (
              <li key={i} className="question-item">{q}</li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="panel--empty">No pending checkpoints</div>
      )}

      <div className="form-group">
        <label className="form-label">Response</label>
        <textarea
          className="form-textarea"
          rows={3}
          value={response}
          onChange={(e) => setResponse(e.target.value)}
          placeholder="Enter your response..."
          disabled={!projectId || !sessionId || running}
        />
        <div className="form-row">
          {sessionId && (
            <span className="mono-sm">Session: {sessionId}</span>
          )}
          <button
            className="btn"
            onClick={handleSubmit}
            disabled={!projectId || !sessionId || !response.trim() || running}
          >
            {running ? "Sending..." : "Submit Response"}
          </button>
        </div>
      </div>

      {result && (
        <div className="command-result">
          {result.stdout && <pre className="command-result__stdout">{result.stdout}</pre>}
          {result.stderr && <pre className="command-result__stderr">{result.stderr}</pre>}
        </div>
      )}
    </div>
  );
}

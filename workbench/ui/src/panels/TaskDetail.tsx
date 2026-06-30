import { useEffect, useState } from "react";
import type { TaskDetail as TaskDetailType } from "../types";
import { deleteTask, updateTask } from "../bridge/files";

interface Props {
  task: TaskDetailType | null;
  loading: boolean;
  error: string | null;
  vaultRoot: string | null;
  onChanged?: () => void;
  onDeleted?: () => void;
}

type Tab = "task" | "report" | "review";

export function TaskDetail({ task, loading, error, vaultRoot, onChanged, onDeleted }: Props) {
  const [tab, setTab] = useState<Tab>("task");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    setEditing(false);
    setDraft(task?.content ?? "");
    setLocalError(null);
  }, [task?.path, task?.content]);

  if (loading) return <div className="panel">Loading task...</div>;
  if (error) return <div className="panel panel--error">{error}</div>;
  if (!task) return <div className="panel panel--empty">Select a task to inspect</div>;

  const fm = task.frontmatter;
  const tabs: { key: Tab; label: string; available: boolean }[] = [
    { key: "task", label: "Task", available: true },
    { key: "report", label: "Report", available: !!task.report_content },
    { key: "review", label: "Review", available: !!task.review_content },
  ];

  return (
    <div className="panel task-detail">
      <div className="task-detail__header">
        <h3 className="panel__title">{task.filename.replace(/\.md$/, "")}</h3>
        <div className="task-detail__actions">
          {tab === "task" && !editing && (
            <button
              className="btn btn--sm"
              onClick={() => setEditing(true)}
              disabled={saving || deleting}
            >
              Edit
            </button>
          )}
          {tab === "task" && editing && (
            <>
              <button
                className="btn btn--sm btn--primary"
                onClick={async () => {
                  setSaving(true);
                  setLocalError(null);
                  try {
                    await updateTask(task.path, draft, vaultRoot ?? "");
                    setEditing(false);
                    onChanged?.();
                  } catch (e) {
                    setLocalError(String(e));
                  } finally {
                    setSaving(false);
                  }
                }}
                disabled={saving || deleting}
              >
                {saving ? "Saving..." : "Save"}
              </button>
              <button
                className="btn btn--sm"
                onClick={() => {
                  setDraft(task.content);
                  setEditing(false);
                  setLocalError(null);
                }}
                disabled={saving || deleting}
              >
                Cancel
              </button>
            </>
          )}
          {!confirmDelete ? (
            <button
              className="btn btn--sm btn--danger"
              onClick={() => setConfirmDelete(true)}
              disabled={saving || deleting}
            >
              Delete
            </button>
          ) : (
            <>
              <span className="model-row__confirm-text">Delete {task.filename}?</span>
              <button
                className="btn btn--sm btn--danger"
                onClick={async () => {
                  setDeleting(true);
                  setLocalError(null);
                  try {
                    await deleteTask(task.path, vaultRoot ?? "");
                    setConfirmDelete(false);
                    onDeleted?.();
                  } catch (e) {
                    setLocalError(String(e));
                  } finally {
                    setDeleting(false);
                  }
                }}
                disabled={deleting}
              >
                {deleting ? "Deleting..." : "Yes"}
              </button>
              <button
                className="btn btn--sm"
                onClick={() => setConfirmDelete(false)}
                disabled={deleting}
              >
                No
              </button>
            </>
          )}
        </div>
      </div>

      {localError && <div className="mgmt-error">{localError}</div>}

      <div className="task-detail__meta">
        {renderField("Status", fm.status)}
        {renderField("Escalation", fm.escalation_tier)}
        {renderField("Revision", fm.revision)}
        {renderField("Priority", fm.priority)}
        {renderField("Assigned", fm.assigned_to)}
        {renderField("Queued by", fm.queued_by)}
        {renderField("Type", fm.type)}
      </div>

      {Array.isArray(fm.subsystems) && (
        <div className="task-detail__subsystems">
          {(fm.subsystems as string[]).map((s) => (
            <span key={s} className="badge badge--sub">{s}</span>
          ))}
        </div>
      )}

      <div className="tab-bar">
        {tabs.map((t) => (
          <button
            key={t.key}
            className={`tab ${tab === t.key ? "tab--active" : ""} ${!t.available ? "tab--disabled" : ""}`}
            onClick={() => t.available && setTab(t.key)}
            disabled={!t.available}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="task-detail__content">
        {tab === "task" && editing && (
          <textarea
            className="form-textarea task-detail__editor"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            spellCheck={false}
          />
        )}
        {tab === "task" && !editing && <pre className="content-pre">{task.content}</pre>}
        {tab === "report" && (
          <pre className="content-pre">{task.report_content ?? "No report found"}</pre>
        )}
        {tab === "review" && (
          <pre className="content-pre">{task.review_content ?? "No review found"}</pre>
        )}
      </div>
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

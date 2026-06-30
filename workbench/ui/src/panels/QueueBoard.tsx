import type { QueueState, TaskSummary } from "../types";
import { TaskCard } from "../components/TaskCard";
import { useEffect } from "react";

interface Props {
  queue: QueueState;
  loading: boolean;
  selectedTaskPath: string | null;
  onSelectTask: (path: string) => void;
  onRefresh: () => void;
}

const SECTIONS: { key: keyof QueueState; label: string; color: string }[] = [
  { key: "open", label: "Open", color: "var(--color-open)" },
  { key: "claimed", label: "Claimed", color: "var(--color-claimed)" },
  { key: "review_needed", label: "Review Needed", color: "var(--color-review)" },
  { key: "completed", label: "Completed", color: "var(--color-completed)" },
  { key: "blocked", label: "Blocked", color: "var(--color-blocked)" },
];

export function QueueBoard({
  queue,
  loading,
  selectedTaskPath,
  onSelectTask,
  onRefresh,
}: Props) {
  useEffect(() => {
    onRefresh();
  }, [onRefresh]);

  const total =
    queue.open.length +
    queue.claimed.length +
    queue.review_needed.length +
    queue.completed.length +
    queue.blocked.length;

  return (
    <div className="queue-board">
      <div className="queue-board__header">
        <h3 className="panel__title">
          Queue <span className="queue-board__total">{total}</span>
        </h3>
        <button className="btn btn--sm" onClick={onRefresh} disabled={loading}>
          {loading ? "..." : "Refresh"}
        </button>
      </div>
      <div className="queue-board__sections">
        {SECTIONS.map(({ key, label, color }) => {
          const tasks: TaskSummary[] = queue[key];
          if (tasks.length === 0) {
            return (
              <div key={key} className="queue-section queue-section--empty">
                <div className="queue-section__header" style={{ borderLeftColor: color }}>
                  {label}
                </div>
              </div>
            );
          }
          return (
            <div key={key} className="queue-section">
              <div className="queue-section__header" style={{ borderLeftColor: color }}>
                {label}{" "}
                <span className="queue-section__count">{tasks.length}</span>
              </div>
              <div className="queue-section__cards">
                {tasks.map((t) => (
                  <TaskCard
                    key={t.path}
                    task={t}
                    selected={t.path === selectedTaskPath}
                    onClick={() => onSelectTask(t.path)}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

import { memo } from "react";
import type { TaskSummary } from "../types";

interface Props {
  task: TaskSummary;
  selected: boolean;
  onClick: () => void;
}

export const TaskCard = memo(function TaskCard({ task, selected, onClick }: Props) {
  const tier = task.frontmatter.escalation_tier as string | undefined;
  const revision = task.frontmatter.revision as number | undefined;
  const assignedTo = task.frontmatter.assigned_to as string | undefined;
  const priority = task.frontmatter.priority as string | undefined;

  return (
    <div
      className={`task-card ${selected ? "task-card--selected" : ""}`}
      onClick={onClick}
    >
      <div className="task-card__name">{task.filename.replace(/\.md$/, "")}</div>
      {task.goal && <div className="task-card__goal">{task.goal}</div>}
      <div className="task-card__meta">
        {tier && <span className="badge badge--tier">{tier}</span>}
        {priority && <span className="badge badge--priority">{priority}</span>}
        {typeof revision === "number" && revision > 0 && (
          <span className="badge badge--revision">rev {revision}</span>
        )}
        {assignedTo && (
          <span className="badge badge--assigned">{assignedTo}</span>
        )}
      </div>
    </div>
  );
});

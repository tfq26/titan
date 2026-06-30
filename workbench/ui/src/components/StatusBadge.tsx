interface Props {
  status: string;
}

const STATUS_COLORS: Record<string, string> = {
  open: "var(--color-open)",
  claimed: "var(--color-claimed)",
  "review-needed": "var(--color-review)",
  completed: "var(--color-completed)",
  blocked: "var(--color-blocked)",
  active: "var(--color-active)",
  registered: "var(--color-registered)",
  configured: "var(--color-completed)",
  "missing env": "var(--color-blocked)",
  "denied by project": "var(--color-blocked)",
  "escalation only": "var(--color-review)",
};

export function StatusBadge({ status }: Props) {
  const color = STATUS_COLORS[status] ?? "var(--color-muted)";
  return (
    <span className="status-badge" style={{ borderColor: color, color }}>
      {status}
    </span>
  );
}

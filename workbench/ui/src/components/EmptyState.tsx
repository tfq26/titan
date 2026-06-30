interface Props {
  icon?: string;
  title: string;
  hint: string;
}

export function EmptyState({ icon, title, hint }: Props) {
  return (
    <div className="empty-state">
      {icon && <div className="empty-state__icon">{icon}</div>}
      <div className="empty-state__title">{title}</div>
      <div className="empty-state__hint">{hint}</div>
    </div>
  );
}

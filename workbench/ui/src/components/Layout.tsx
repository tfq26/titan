import type { ReactNode } from "react";

interface Props {
  rail: ReactNode;
  center?: ReactNode;
  detail: ReactNode;
  railCollapsed?: boolean;
  onToggleRail?: () => void;
}

export function Layout({ rail, center, detail, railCollapsed, onToggleRail }: Props) {
  const railClass = `layout__rail${railCollapsed ? " layout__rail--collapsed" : ""}`;
  return (
    <div className="layout">
      <aside className={railClass}>
        {rail}
        <button className="rail-toggle" onClick={onToggleRail} title={railCollapsed ? "Show sidebar" : "Hide sidebar"}>
          {railCollapsed ? "»" : "«"}
        </button>
      </aside>
      {center && <section className="layout__center">{center}</section>}
      <section className="layout__detail">{detail}</section>
    </div>
  );
}

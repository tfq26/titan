import type { ChatHistorySummary } from "../types";

interface Props {
  histories: ChatHistorySummary[];
  onOpenHistory: (history: ChatHistorySummary) => void;
  onClose: () => void;
}

export function HistoryDrawer({ histories, onOpenHistory, onClose }: Props) {
  return (
    <div className="history-drawer">
      <div className="history-drawer__header">
        <div className="history-drawer__title">Chat History</div>
        <button className="history-drawer__close" onClick={onClose}>
          &times;
        </button>
      </div>
      <div className="history-drawer__body">
        {histories.length > 0 ? (
          <div className="history-list">
            {histories.map((history) => (
              <button
                key={history.history_path}
                className="history-item"
                onClick={() => onOpenHistory(history)}
                title={history.history_path}
              >
                <div className="history-item__top">
                  <span className="history-item__project">{history.project_name}</span>
                  <span className="history-item__date">
                    {new Date(history.updated_at_ms).toLocaleString()}
                  </span>
                </div>
                <div className="history-item__preview">{history.preview}</div>
                <div className="history-item__meta">
                  <span>{history.entry_count} entries</span>
                  {history.session_id && <span>Session {history.session_id}</span>}
                  {history.current_node && <span>{history.current_node}</span>}
                  {history.final_decision && <span>{history.final_decision}</span>}
                  {history.archived && <span>Archived</span>}
                </div>
              </button>
            ))}
          </div>
        ) : (
          <div className="history-empty">No prior chats have been archived yet.</div>
        )}
      </div>
    </div>
  );
}

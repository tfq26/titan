import { useState, useEffect, useCallback } from "react";
import type {
  ChatHistorySummary,
  ChatSessionSummary,
  CommandResult,
  PanelTab,
} from "./types";
import { Layout } from "./components/Layout";
import { ProjectSelector } from "./panels/ProjectSelector";
import { QueueBoard } from "./panels/QueueBoard";
import { TaskDetail } from "./panels/TaskDetail";
import { NewChat } from "./panels/NewChat";
import { ConfigurePanel } from "./panels/ConfigurePanel";
import { WorkbenchActions } from "./panels/WorkbenchActions";
import { ApprovalPanel } from "./panels/ApprovalPanel";
import { EmptyState } from "./components/EmptyState";
import { useProjects } from "./hooks/useProjects";
import { useQueue } from "./hooks/useQueue";
import { useRouting } from "./hooks/useRouting";
import { useTaskDetail } from "./hooks/useTaskDetail";
import { getWorkbenchRoot, getTraceConfig } from "./bridge/system";
import { listChatHistories } from "./bridge/files";
import { parseSessionOutput } from "./lib/parseSession";

const TABS: { key: PanelTab; label: string }[] = [
  { key: "chat", label: "Chat" },
  { key: "queue", label: "Queue" },
  { key: "configure", label: "Configure" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<PanelTab>("chat");
  const [showTask, setShowTask] = useState(false);
  const [selectedTaskPath, setSelectedTaskPath] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [chatSession, setChatSession] = useState<ChatSessionSummary | null>(null);
  const [pendingQuestions, setPendingQuestions] = useState<string[]>([]);
  const [workbenchRoot, setWorkbenchRoot] = useState("");
  const [tracingEnabled, setTracingEnabled] = useState(false);
  const [autoRelay, setAutoRelay] = useState(true);
  const [responseMode, setResponseMode] = useState<"brief" | "explain">("brief");
  const [chatHistories, setChatHistories] = useState<ChatHistorySummary[]>([]);
  const [railCollapsed, setRailCollapsed] = useState(false);

  const {
    projects,
    selected,
    selectedId,
    setSelectedId,
    projectConfig,
    refreshConfig,
    addProject,
  } = useProjects();
  const vaultRoot = selected?.vault_root ?? null;
  const { queue, loading: queueLoading, refresh: refreshQueue } =
    useQueue(vaultRoot);
  const { routing, envStatus, refresh: refreshRouting } = useRouting();
  const {
    task: taskDetail,
    loading: taskLoading,
    error: taskError,
    loadTask,
    clear: clearTask,
  } = useTaskDetail(vaultRoot);

  useEffect(() => {
    getWorkbenchRoot().then(setWorkbenchRoot).catch(() => {});
    getTraceConfig()
      .then((c) => setTracingEnabled(c.tracing_enabled))
      .catch(() => {});
    listChatHistories()
      .then(setChatHistories)
      .catch(() => {});
  }, []);

  useEffect(() => {
    setChatSession(null);
    setSessionId(null);
    setShowTask(false);
  }, [selectedId]);

  useEffect(() => {
    if (activeTab !== "chat") {
      setChatSession(null);
    }
  }, [activeTab]);

  const refreshChatHistories = useCallback(() => {
    listChatHistories()
      .then(setChatHistories)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (vaultRoot) refreshQueue();
  }, [vaultRoot, refreshQueue]);

  const handleSelectTask = useCallback(
    (path: string) => {
      setSelectedTaskPath(path);
      loadTask(path);
      setShowTask(true);
    },
    [loadTask]
  );

  const handleTaskChanged = useCallback(() => {
    if (selectedTaskPath) {
      loadTask(selectedTaskPath);
    }
    refreshQueue();
  }, [loadTask, refreshQueue, selectedTaskPath]);

  const handleTaskDeleted = useCallback(() => {
    setSelectedTaskPath(null);
    clearTask();
    setShowTask(false);
    refreshQueue();
  }, [clearTask, refreshQueue]);

  const handleNewChat = useCallback(() => {
    refreshChatHistories();
  }, [refreshChatHistories]);

  const handleOpenHistory = useCallback(
    (history: ChatHistorySummary) => {
      if (history.project_id && history.project_id !== selectedId) {
        setSelectedId(history.project_id);
      }
      if (history.session_id) {
        setSessionId(history.session_id);
      }
      if (history.session_id) {
        setActiveTab("chat");
      }
    },
    [selectedId, setSelectedId]
  );

  const handleCommandResult = useCallback(
    (result: CommandResult, sid?: string) => {
      const parsed = result.stdout ? parseSessionOutput(result.stdout) : null;
      if (sid) {
        setSessionId(sid);
      } else if (parsed?.session_id) {
        setSessionId(parsed.session_id);
      }
      setPendingQuestions(parsed?.human_questions ?? []);
    },
    []
  );

  const handleChatResult = useCallback(
    (result: CommandResult) => handleCommandResult(result),
    [handleCommandResult]
  );

  const visibleChatSession = activeTab === "chat" ? chatSession : null;

  const rail = (
    <>
      <div className="rail-header">
        <h2 className="app-title">Workbench</h2>
      </div>
      <ProjectSelector
        projects={projects}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onAddProject={addProject}
      />

      {visibleChatSession && (
        <div className="rail-section">
          <div className="rail-section__title">Session</div>
          <div className="rail-fields">
            <div className="rail-field">
              <span className="rail-field__label">Speaker</span>
              <span className="rail-field__value">{visibleChatSession.current_speaker}</span>
            </div>
            <div className="rail-field">
              <span className="rail-field__label">Mode</span>
              <span className="rail-field__value">{visibleChatSession.response_mode}</span>
            </div>
            <div className="rail-field">
              <span className="rail-field__label">Turns</span>
              <span className="rail-field__value">{visibleChatSession.turn_count}</span>
            </div>
            <div className="rail-field">
              <span className="rail-field__label">Relay</span>
              <span className="rail-field__value">{visibleChatSession.relay_enabled ? "on" : "off"}</span>
            </div>
          </div>
        </div>
      )}

      <div className="rail-section rail-panel">
        <div className="rail-section__title">Actions</div>
        <WorkbenchActions
          projectId={selectedId}
          vaultRoot={vaultRoot}
          workbenchRoot={workbenchRoot}
          onRefreshQueue={refreshQueue}
        />
      </div>

      <div className="rail-section rail-panel">
        <div className="rail-section__title">
          Approval
          {pendingQuestions.length > 0 && (
            <span className="rail-badge">{pendingQuestions.length}</span>
          )}
        </div>
        <ApprovalPanel
          projectId={selectedId}
          sessionId={sessionId}
          pendingQuestions={pendingQuestions}
        />
      </div>

      <div className="rail-footer">
        <div className="rail-indicator">
          <span
            className={`status-dot ${tracingEnabled ? "status-dot--ok" : "status-dot--missing"}`}
          />
          Tracing {tracingEnabled ? "on" : "off"}
        </div>
      </div>
    </>
  );

  const detail = (
    <>
      <div className="tab-bar">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`tab tab--${t.key} ${activeTab === t.key ? "tab--active" : ""}`}
            onClick={() => setActiveTab(t.key)}
          >
            {t.label}
          </button>
        ))}
        {showTask && (
          <button
            className={`tab tab--task ${activeTab === "task" ? "tab--active" : ""}`}
            onClick={() => setActiveTab("task")}
          >
            Detail
          </button>
        )}
        <div className="tab-bar__spacer" />
        {activeTab === "chat" && (
          <div className="tab-bar__controls">
            <button
              type="button"
              className={`tab tab--control ${autoRelay ? "tab--control-active" : ""}`}
              onClick={() => setAutoRelay((current) => !current)}
              title="Toggle automatic model handoffs"
            >
              Relay {autoRelay ? "on" : "off"}
            </button>
            <button
              type="button"
              className={`tab tab--control ${responseMode === "explain" ? "tab--control-active" : ""}`}
              onClick={() => setResponseMode((current) => (current === "brief" ? "explain" : "brief"))}
              title="Toggle response verbosity"
            >
              Response {responseMode}
            </button>
          </div>
        )}
      </div>
      <div className="detail-area">
        {activeTab === "chat" && (
          <NewChat
            projectId={selectedId}
            routing={routing}
            autoRelay={autoRelay}
            responseMode={responseMode}
            onToggleResponseMode={() =>
              setResponseMode((current) => (current === "brief" ? "explain" : "brief"))
            }
            onResult={handleChatResult}
            onNewChat={handleNewChat}
            onSessionChange={setChatSession}
            onQueueRefresh={refreshQueue}
            histories={chatHistories}
            onOpenHistory={handleOpenHistory}
          />
        )}
        {activeTab === "queue" && (
          <div className="queue-tab">
            <div className="queue-tab__header">
              <h2 className="queue-tab__title">Queue</h2>
              <div className="queue-tab__subtitle">
                Task queue for the selected project
              </div>
            </div>
            <div className="queue-tab__content">
              {queue && queue.open.length + queue.claimed.length + queue.review_needed.length + queue.completed.length + queue.blocked.length > 0 ? (
                <QueueBoard
                  queue={queue}
                  loading={queueLoading}
                  selectedTaskPath={selectedTaskPath}
                  onSelectTask={handleSelectTask}
                  onRefresh={refreshQueue}
                />
              ) : (
                <EmptyState
                  icon="📋"
                  title="No tasks yet"
                  hint="Send a message in the Chat tab or use the /queue command to create tasks."
                />
              )}
            </div>
          </div>
        )}
        {activeTab === "task" && (
          <div className="detail-scroll">
            <TaskDetail
              task={taskDetail}
              loading={taskLoading}
              error={taskError}
              vaultRoot={vaultRoot}
              onChanged={handleTaskChanged}
              onDeleted={handleTaskDeleted}
            />
          </div>
        )}
        {activeTab === "configure" && (
          <ConfigurePanel
            routing={routing}
            envStatus={envStatus}
            projectConfig={projectConfig}
            selectedProjectId={selectedId}
            vaultRoot={vaultRoot}
            onRefreshRouting={refreshRouting}
            onRefreshProjectConfig={refreshConfig}
          />
        )}
      </div>
    </>
  );

  return (
    <Layout
      rail={rail}
      detail={detail}
      railCollapsed={railCollapsed}
      onToggleRail={() => setRailCollapsed((c) => !c)}
    />
  );
}

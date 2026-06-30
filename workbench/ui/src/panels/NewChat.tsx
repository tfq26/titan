import { useState, useRef, useEffect, useCallback, useMemo, memo, type ReactNode } from "react";
import type {
  ChatHistorySummary,
  ChatSessionSummary,
  CommandResult,
  SessionMode,
  RoutingConfig,
  ResponseMode,
} from "../types";
import { SESSION_MODE_LABELS } from "../types";
import { runRequest, runChat } from "../bridge/cli";
import { saveChatHistory, loadChatHistory, startNewChat } from "../bridge/files";
import { parseSessionOutput, type ParsedSession } from "../lib/parseSession";
import { parseChatReply, type ChatHandoff, type ChatPlanProposal, type ChatTaskProposal } from "../lib/chatRelay";
import { looksLikePlanKickoff } from "../lib/kickoff";
import { humanizeLabel, speakerColor } from "../lib/speakers";
import { HistoryDrawer } from "./HistoryDrawer";
import { listen } from "@tauri-apps/api/event";
import type {
  DiscourseLinePayload,
  DiscourseCompletePayload,
  DiscourseStartPayload,
  DiscourseTurnStartPayload,
  DiscourseTokenPayload,
  DiscourseTurnEndPayload,
  DiscourseDonePayload,
} from "../types";
import { runDiscourse } from "../bridge/cli";

interface Props {
  projectId: string | null;
  routing: RoutingConfig | null;
  autoRelay: boolean;
  responseMode: ResponseMode;
  onToggleResponseMode: () => void;
  onResult?: (result: CommandResult) => void;
  onNewChat?: () => void;
  onSessionChange?: (summary: ChatSessionSummary | null) => void;
  onQueueRefresh?: () => void;
  histories?: ChatHistorySummary[];
  onOpenHistory?: (history: ChatHistorySummary) => void;
}

// Destructure in component function is handled inside the function body
// (the props object is destructured in the function parameters below)

interface ChatEntry {
  id: number;
  role: "human" | "assistant" | "status";
  content: string;
  replyToId?: number | null;
  mode?: SessionMode;
  result?: CommandResult;
  speaker?: string;
  modelRole?: string;
  handoffs?: ChatHandoff[];
  task?: ChatTaskProposal | null;
  plan?: ChatPlanProposal | null;
  parsed?: ParsedSession;
  displayText?: string;
}

interface DiscourseTurn {
  role: string;
  nickname: string;
  text: string;
  complete: boolean;
  inputTokens?: number;
  outputTokens?: number;
}

interface MentionTarget {
  name: string;
  label: string;
  role: string;
  speaker: string;
  roleLabel: string;
}

type SlashCommand =
  | { cmd: string; label: string; kind: "mode"; mode: SessionMode }
  | { cmd: string; label: string; kind: "response"; responseMode: ResponseMode };

const SLASH_COMMANDS: SlashCommand[] = [
  { cmd: "plan", kind: "mode", mode: "plan", label: "Plan Kickoff" },
  { cmd: "queue", kind: "mode", mode: "queue", label: "Queue Task" },
  { cmd: "review", kind: "mode", mode: "review", label: "Review Work" },
  { cmd: "ask", kind: "mode", mode: "ask", label: "Ask Team" },
  { cmd: "general", kind: "mode", mode: "general", label: "General Request" },
  { cmd: "brief", kind: "response", responseMode: "brief", label: "Brief responses" },
  { cmd: "explain", kind: "response", responseMode: "explain", label: "Explain responses" },
];

const MODES: SessionMode[] = ["general", "plan", "queue", "review", "ask"];

let nextId = 0;

function resolveAssistantText({
  stdout,
  stderr,
  parsedText,
  parsedSummary,
  taskSummary,
  planSummary,
}: {
  stdout: string;
  stderr: string;
  parsedText?: string;
  parsedSummary?: string;
  taskSummary?: string;
  planSummary?: string;
}) {
  const cleanedParsedText = parsedText?.trim() ?? "";
  const cleanedParsedSummary = parsedSummary?.trim() ?? "";
  const cleanedStdout = stdout.trim();
  const cleanedStderr = stderr.trim();

  if (!cleanedParsedText && planSummary?.trim()) {
    return planSummary.trim();
  }

  if (!cleanedParsedText && taskSummary?.trim()) {
    return taskSummary.trim();
  }

  return (
    cleanedParsedText ||
    cleanedParsedSummary ||
    cleanedStdout ||
    cleanedStderr ||
    "No assistant text returned."
  );
}

function nextPaint() {
  return new Promise<void>((resolve) => {
    window.requestAnimationFrame(() => resolve());
  });
}

function summarizeTask(task: ChatTaskProposal): string {
  const title = task.title.trim();
  const goal = task.goal.trim();
  if (title) {
    return `Queued task: ${title}`;
  }
  if (goal) {
    return "Queued task";
  }
  return "Queued task";
}

function summarizePlan(plan: ChatPlanProposal): string {
  const title = plan.title.trim();
  const count = plan.tasks.length;
  if (title && count > 1) {
    return `Queued plan: ${title} (${count} slices)`;
  }
  if (title) {
    return `Queued plan: ${title}`;
  }
  if (count > 1) {
    return `Queued plan (${count} slices)`;
  }
  return "Queued plan";
}

export function NewChat({
  projectId,
  routing,
  autoRelay,
  responseMode,
  onToggleResponseMode,
  onResult,
  onNewChat,
  onSessionChange,
  onQueueRefresh,
  histories,
  onOpenHistory,
}: Props) {
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState<SessionMode>("general");
  const [history, setHistory] = useState<ChatEntry[]>([]);
  const [running, setRunning] = useState(false);
  const [showModes, setShowModes] = useState(false);
  const [showSlash, setShowSlash] = useState(false);
  const [slashFilter, setSlashFilter] = useState("");
  const [showMention, setShowMention] = useState(false);
  const [mentionFilter, setMentionFilter] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [discourseTurns, setDiscourseTurns] = useState<DiscourseTurn[]>([]);
  const [discourseFallbackLines, setDiscourseFallbackLines] = useState<string[]>([]);
  const [discourseRunning, setDiscourseRunning] = useState(false);
  const onResultRef = useRef(onResult);
  onResultRef.current = onResult;

  const roleTargets = useMemo(() => buildRoleTargets(routing), [routing]);
  const workerSpeaker = roleTargets.worker?.displayName ?? "worker";
  const kickoffSuggested = useMemo(() => looksLikePlanKickoff(message), [message]);
  const kickoffActive = mode === "plan" || kickoffSuggested;
  const kickoffLabel = mode === "plan" ? "Plan kickoff" : "Plan kickoff detected";
  const kickoffHelper = mode === "plan"
    ? "Starting from the existing plan/current-state note. Smallest slice first, with explicit handoffs as needed."
    : "This looks plan-oriented. Switch to Plan Kickoff if you want the queue and handoff posture to match.";
  const mentions: MentionTarget[] = routing
    ? [
        { name: "everyone", label: "All Models", role: "", speaker: "All Models", roleLabel: "" },
        ...routing.roles.map((r) => {
          const target = roleTargets[r.role];
          const speaker = target?.displayName ?? r.role;
          const modelNickname = target?.nickname ?? r.role;
          return { name: modelNickname, label: r.role, role: r.role, speaker, roleLabel: target?.roleLabel ?? humanizeLabel(r.role) };
        }),
      ]
    : [];

  const filteredMentions = mentions.filter((m) =>
    m.name.toLowerCase().startsWith(mentionFilter.toLowerCase())
  );
  const threadedHistory = useMemo(() => buildThreadRoots(history), [history]);
  const chatContext = useMemo(() => buildChatContext(history), [history]);
  const chatTranscript = useMemo(
    () => buildChatTranscript(threadedHistory, projectId),
    [projectId, threadedHistory]
  );

  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const saveTimerRef = useRef<number | null>(null);

  const scrollToBottom = useCallback(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight;
    }
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [history, running, scrollToBottom]);

  useEffect(() => {
    if (!projectId) return;
    loadChatHistory(projectId)
      .then((json) => {
        try {
          const entries = JSON.parse(json) as ChatEntry[];
          if (entries.length > 0) {
            const maxId = entries.reduce((max, entry) => Math.max(max, entry.id ?? 0), -1);
            nextId = Math.max(nextId, maxId + 1);
            setHistory(normalizeHistory(entries, roleTargets));
          }
        } catch (_) {}
      })
      .catch(() => {});
  }, [projectId, roleTargets]);

  useEffect(() => {
    onSessionChange?.(
      buildChatSessionSummary({
        history,
        projectId,
        responseMode,
        autoRelay,
        running,
      })
    );
  }, [autoRelay, history, onSessionChange, projectId, responseMode, running]);

  useEffect(() => {
    if (!projectId) return;
    if (saveTimerRef.current != null) {
      window.clearTimeout(saveTimerRef.current);
    }
    saveTimerRef.current = window.setTimeout(() => {
      saveChatHistory(projectId, JSON.stringify(history)).catch(() => {});
    }, 2000);

    return () => {
      if (saveTimerRef.current != null) {
        window.clearTimeout(saveTimerRef.current);
      }
    };
  }, [projectId, history]);

  useEffect(() => {
    const unlistenFallback = listen<DiscourseLinePayload>("discourse-line", (event) => {
      setDiscourseFallbackLines((prev) => [...prev, event.payload.text]);
    });
    const unlistenStart = listen<DiscourseStartPayload>("discourse-start", () => {
      // Discourse started — no state change needed, already in discourseRunning
    });
    const unlistenTurnStart = listen<DiscourseTurnStartPayload>("discourse-turn-start", (event) => {
      setDiscourseTurns((prev) => [
        ...prev,
        { role: event.payload.role, nickname: event.payload.nickname, text: "", complete: false },
      ]);
    });
    const unlistenToken = listen<DiscourseTokenPayload>("discourse-token", (event) => {
      setDiscourseTurns((prev) => {
        const turns = [...prev];
        if (turns.length === 0) return prev;
        const last = { ...turns[turns.length - 1] };
        last.text += event.payload.text;
        turns[turns.length - 1] = last;
        return turns;
      });
    });
    const unlistenTurnEnd = listen<DiscourseTurnEndPayload>("discourse-turn-end", (event) => {
      setDiscourseTurns((prev) => {
        const turns = [...prev];
        if (turns.length === 0) return prev;
        const last = { ...turns[turns.length - 1] };
        last.text = event.payload.text;
        last.complete = true;
        last.inputTokens = event.payload.input_tokens;
        last.outputTokens = event.payload.output_tokens;
        turns[turns.length - 1] = last;
        return turns;
      });
    });
    const unlistenDone = listen<DiscourseDonePayload>("discourse-done", () => {
      setDiscourseRunning(false);
      setDiscourseTurns((prev) => {
        const transcript = prev
          .map((t) => `${t.nickname}: ${t.text}`)
          .join("\n\n");
        onResultRef.current?.({
          stdout: transcript,
          stderr: "",
          exit_code: 0,
        });
        return prev;
      });
    });
    const unlistenComplete = listen<DiscourseCompletePayload>("discourse-complete", () => {
      setDiscourseRunning(false);
    });
    return () => {
      unlistenFallback.then((fn) => fn());
      unlistenStart.then((fn) => fn());
      unlistenTurnStart.then((fn) => fn());
      unlistenToken.then((fn) => fn());
      unlistenTurnEnd.then((fn) => fn());
      unlistenDone.then((fn) => fn());
      unlistenComplete.then((fn) => fn());
    };
  }, []);

  const handleInputChange = (value: string) => {
    setMessage(value);
    if (value.startsWith("/") && !value.includes("\n")) {
      const after = value.slice(1).split(/\s/)[0].toLowerCase();
      setSlashFilter(after);
      setShowSlash(true);
      setShowMention(false);
    } else if (value.startsWith("@") && !value.includes("\n")) {
      const after = value.slice(1).split(/\s/)[0].toLowerCase();
      setMentionFilter(after);
      setShowMention(true);
      setShowSlash(false);
    } else {
      setShowSlash(false);
      setShowMention(false);
    }
  };

  const selectMention = (name: string) => {
    setShowMention(false);
    const rest = message.replace(/^@\S*\s*/, "");
    setMessage(`@${name} ${rest}`);
    inputRef.current?.focus();
  };

  const selectSlashCommand = (command: SlashCommand) => {
    if (command.kind === "mode") {
      setMode(command.mode);
    } else {
      onToggleResponseMode();
    }
    setShowSlash(false);
    const rest = message.replace(/^\/\S*\s*/, "");
    setMessage(rest);
    inputRef.current?.focus();
  };

  const filteredCommands = SLASH_COMMANDS.filter((c) =>
    c.cmd.startsWith(slashFilter)
  );

  const handleClear = useCallback(() => {
    setHistory([]);
    setMessage("");
    setShowSlash(false);
    onSessionChange?.(null);
    if (projectId) {
      saveChatHistory(projectId, "[]").catch(() => {});
    }
  }, [onSessionChange, projectId]);

  const handleNewChat = useCallback(async () => {
    const currentHistory = JSON.stringify(history);
    if (projectId) {
      try {
        await startNewChat(projectId, currentHistory);
        await saveChatHistory(projectId, "[]");
        setHistory([]);
        setMessage("");
        setMode("general");
        setShowModes(false);
        setShowSlash(false);
        setShowMention(false);
        onSessionChange?.(null);
        onNewChat?.();
      } catch (e) {
        setHistory((prev) => [...prev, { id: nextId++, role: "status", content: String(e) }]);
      }
      return;
    }
    setHistory([]);
    setMessage("");
    setMode("general");
    setShowModes(false);
    setShowSlash(false);
    setShowMention(false);
    onSessionChange?.(null);
  }, [onSessionChange, onNewChat, projectId, history]);

  const handleSend = () => {
    if (!projectId || !message.trim()) return;
    window.setTimeout(() => {
      void runSend();
    }, 0);
  };

  const runSend = async () => {
    if (!projectId || !message.trim()) return;

    if (message.trim().toLowerCase() === "/clear") {
      handleClear();
      return;
    }

    let actualMode = mode;
    let actualMessage = message.trim();

    const slashMatch = actualMessage.match(/^\/(\w+)\s*([\s\S]*)/);
    if (slashMatch) {
      const commandName = slashMatch[1].toLowerCase();
      const remainder = slashMatch[2].trim();
      const found = SLASH_COMMANDS.find((c) => c.cmd === commandName);
      if (found) {
        if (found.kind === "mode") {
          actualMode = found.mode;
          actualMessage = remainder;
        } else {
          if (responseMode !== found.responseMode) {
            onToggleResponseMode();
          }
          if (!remainder) {
            setMessage("");
            setShowSlash(false);
            return;
          }
          actualMessage = remainder;
        }
      }
    } else if (actualMessage.match(/^\/(\w+)$/)) {
      const found = SLASH_COMMANDS.find((c) => c.cmd === actualMessage.slice(1).toLowerCase());
      if (found) {
        if (found.kind === "mode") {
          setMode(found.mode);
        } else {
          if (responseMode !== found.responseMode) {
            onToggleResponseMode();
          }
        }
        setMessage("");
        setShowSlash(false);
        return;
      }
    }

    // Parse @mention
    let targetRoles: { role: string; nickname: string; speaker: string }[] = [];
    const mentionMatch = actualMessage.match(/^@(\S+)\s+([\s\S]*)/);
    if (mentionMatch) {
      const name = mentionMatch[1].toLowerCase();
      actualMessage = mentionMatch[2].trim();
      if (name === "everyone") {
        targetRoles = mentions
          .filter((m) => m.role)
          .map((m) => ({ role: m.role, nickname: m.name, speaker: m.speaker ?? m.name }));
      } else {
        const found = mentions.find((m) => m.name.toLowerCase() === name);
        if (found?.role) {
          targetRoles = [
            {
              role: found.role,
              nickname: found.name,
              speaker: found.speaker ?? found.name,
            },
          ];
        }
      }
    }

    if (!actualMessage) return;

    const displayContent = mentionMatch
      ? `@${mentionMatch[1]} ${actualMessage}`
      : actualMessage;

    const parentId = nextId++;
    setHistory((prev) => [
      ...prev,
      {
        id: parentId,
        role: "human",
        content: displayContent,
        mode: actualMode,
      },
    ]);
    setMessage("");
    setShowSlash(false);
    setShowMention(false);
    setRunning(true);
    await nextPaint();

    // ── Discourse mode ───────────────────────────────────────────
    const discourseMatch = actualMessage.match(/^\/discourse\s+([\s\S]*)/);
    if (discourseMatch) {
      actualMessage = discourseMatch[1];
      if (!actualMessage) {
        setRunning(false);
        return;
      }
      setDiscourseTurns([]);
      setDiscourseFallbackLines([]);
      setDiscourseRunning(true);
      await nextPaint();
      try {
        await runDiscourse(projectId, actualMessage);
      } catch (e) {
        setDiscourseFallbackLines((prev) => [...prev, `[error] ${e}`]);
        setDiscourseRunning(false);
      }
      setRunning(false);
      return;
    }

    const prefix =
      actualMode !== "general"
        ? `[${SESSION_MODE_LABELS[actualMode]}] `
        : "";

    try {
      if (actualMode === "queue") {
        const r = await runRequest(projectId, `${prefix}${actualMessage}`);
        const parsed = parseSessionOutput(r.stdout);
        const displayText = resolveAssistantText({
          stdout: r.stdout,
          stderr: r.stderr,
          parsedText: parsed.message_text,
          parsedSummary: parsed.summary_text,
        });
        setHistory((prev) => [
          ...prev,
          {
            id: nextId++,
            role: "assistant",
            content: "",
            result: r,
            speaker: workerSpeaker,
            modelRole: "worker",
            parsed,
            displayText,
          },
        ]);
        onResult?.(r);
        onQueueRefresh?.();
      } else if (targetRoles.length > 0) {
        for (const target of targetRoles) {
          await deliverChatTurn({
            projectId,
            initialMessage: `${prefix}${actualMessage}`,
            seedMessage: `${prefix}${actualMessage}`,
            role: target.role,
            speaker: target.speaker,
            parentId,
            depth: 0,
            canRelay: autoRelay && targetRoles.length === 1,
            responseMode,
            chatContext,
          });
        }
      } else {
        await deliverChatTurn({
          projectId,
          initialMessage: `${prefix}${actualMessage}`,
          seedMessage: `${prefix}${actualMessage}`,
          role: "worker",
          speaker: workerSpeaker,
          parentId,
          depth: 0,
          canRelay: autoRelay,
          responseMode,
          chatContext,
        });
      }
    } catch (e) {
      setHistory((prev) => [
        ...prev,
        { id: nextId++, role: "status", content: String(e) },
      ]);
      onResult?.({ stdout: "", stderr: String(e), exit_code: 1 });
    } finally {
      setRunning(false);
    }
  };

  async function deliverChatTurn({
    projectId: projectIdArg,
    initialMessage,
    seedMessage,
    role,
    speaker,
    parentId,
    depth,
    canRelay,
    responseMode: responseModeArg,
    chatContext,
  }: {
    projectId: string;
    initialMessage: string;
    seedMessage: string;
    role: string;
    speaker: string;
    parentId: number;
    depth: number;
    canRelay: boolean;
    responseMode: ResponseMode;
    chatContext: string;
  }) {
    const r = await runChat(projectIdArg, initialMessage, role, responseModeArg, chatContext);
    const parsed = parseChatReply(r.stdout);
    const session = parseSessionOutput(r.stdout);
    const messageText = resolveAssistantText({
      stdout: r.stdout,
      stderr: r.stderr,
      parsedText: parsed.text || session.message_text,
      parsedSummary: session.summary_text,
      taskSummary: parsed.task ? summarizeTask(parsed.task) : "",
      planSummary: parsed.plan ? summarizePlan(parsed.plan) : "",
    });

    const handoffs = parsed.handoffs.filter((handoff) => handoff.role !== role);
    const entryId = nextId++;

    setHistory((prev) => [
      ...prev,
      {
        id: entryId,
        role: "assistant",
        content: "",
        replyToId: parentId,
        result: r,
        speaker,
        modelRole: role,
        handoffs,
        task: parsed.task,
        plan: parsed.plan,
        parsed: session,
        displayText: messageText,
      },
    ]);
    onResult?.(r);
    if (parsed.task || parsed.plan) {
      onQueueRefresh?.();
    }

    if (!canRelay || depth >= 3 || handoffs.length === 0) {
      return;
    }

    const next = handoffs[0];
    const nextSpeaker = roleTargets[next.role]?.displayName ?? humanizeLabel(next.role);
    const relayPrompt = buildRelayPrompt({
      fromRole: role,
      fromSpeaker: speaker,
      toRole: next.role,
      originalMessage: seedMessage,
      replyText: messageText,
      reason: next.reason,
    });

    const pingId = nextId++;
    setHistory((prev) => [
      ...prev,
      {
        id: pingId,
        role: "status",
        content: `→ pinging ${nextSpeaker}`,
        replyToId: entryId,
      },
    ]);

    await deliverChatTurn({
      projectId: projectIdArg,
      initialMessage: relayPrompt,
      seedMessage,
      role: next.role,
      speaker: nextSpeaker,
      parentId: pingId,
      depth: depth + 1,
      canRelay,
      responseMode: responseModeArg,
      chatContext,
    });
  }

  const clearMatches = "clear".startsWith(slashFilter);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (showSlash && filteredCommands.length > 0) {
        const first = filteredCommands[0];
        selectSlashCommand(first);
      } else if (showSlash && clearMatches) {
        handleClear();
      } else if (showMention && filteredMentions.length > 0) {
        selectMention(filteredMentions[0].name);
      } else {
        handleSend();
      }
    }
    if (e.key === "Tab" && showSlash && filteredCommands.length > 0) {
      e.preventDefault();
      selectSlashCommand(filteredCommands[0]);
    }
    if (e.key === "Tab" && showSlash && !filteredCommands.length && clearMatches) {
      e.preventDefault();
      handleClear();
    }
    if (e.key === "Tab" && showMention && filteredMentions.length > 0) {
      e.preventDefault();
      selectMention(filteredMentions[0].name);
    }
    if (e.key === "Escape") {
      setShowSlash(false);
      setShowModes(false);
      setShowMention(false);
    }
  };

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <div>
          <div className="chat-header__title-row">
            <div className="chat-header__title">Chat</div>
            {kickoffActive && (
              <span className="chat-header__badge">{kickoffLabel}</span>
            )}
          </div>
          <div className="chat-header__subtitle">
            Start a new thread for the selected project or keep the current one going.
          </div>
          {kickoffActive && (
            <div className="chat-header__helper">
              {kickoffHelper}
            </div>
          )}
        </div>
        <div className="chat-header__actions">
          <CopyButton
            text={chatTranscript}
            label="Copy Chat"
            className="chat-header__button"
            disabled={running || !projectId || !chatTranscript}
            title="Copy the current chat transcript"
          />
          <button
            className="btn btn--ghost chat-header__button"
            onClick={() => setShowHistory(true)}
            disabled={!projectId}
            title="View chat history"
          >
            History
          </button>
          <button
            className="btn btn--ghost chat-header__button"
            onClick={handleNewChat}
            disabled={running || !projectId}
            title="Archive the current chat and start a new one"
          >
            New Chat
          </button>
        </div>
        {showHistory && (
          <HistoryDrawer
            histories={histories ?? []}
            onOpenHistory={(h) => {
              setShowHistory(false);
              onOpenHistory?.(h);
            }}
            onClose={() => setShowHistory(false)}
          />
        )}
      </div>
    <div className="chat-thread" ref={threadRef}>
        {history.length === 0 && !running && !discourseRunning && (
          <div className="chat-empty">
            <div className="chat-empty__title">Workbench Chat</div>
            <div className="chat-empty__hint">
              Send a message or use <code>/</code> commands
            </div>
            <div className="chat-empty__cmds">
              {SLASH_COMMANDS.map((c) => (
                <span key={c.cmd} className="chat-empty__cmd">
                  /{c.cmd}
                </span>
              ))}
              <span className="chat-empty__cmd">/discourse</span>
            </div>
          </div>
        )}
        {threadedHistory.map((entry) => <ThreadNodeView key={entry.id} node={entry} fallbackSpeaker={workerSpeaker} />)}
        {(discourseFallbackLines.length > 0) && (
          <div className="chat-entry chat-entry--discourse">
            <div className="chat-message__identity">
              <div className="chat-message__speaker" style={{ color: '#8b5cf6' }}>Discourse</div>
              <div className="chat-message__role">Multi-agent discussion</div>
            </div>
            <pre className="chat-discourse__pre">{discourseFallbackLines.join('\n')}</pre>
          </div>
        )}
        {(discourseTurns.length > 0 || discourseRunning) && (
          <div className="chat-entry chat-entry--discourse">
            <div className="discourse-conversation">
              {discourseTurns.map((turn, i) => (
                <div key={i} className="discourse-turn">
                  <div className="discourse-turn__header">
                    <div className="discourse-turn__speaker" style={{ color: speakerColor(turn.nickname) }}>
                      {turn.nickname}
                    </div>
                    <div className="discourse-turn__role">{humanizeLabel(turn.role)}</div>
                  </div>
                  <div className="discourse-turn__text chat-markdown">
                    <MarkdownMessage text={turn.text} />
                  </div>
                  {turn.complete && (turn.inputTokens || turn.outputTokens) && (
                    <div className="discourse-turn__tokens">
                      <span className="discourse-turn__token-count">
                        {turn.outputTokens ?? 0}…{turn.inputTokens ?? 0} tokens
                      </span>
                    </div>
                  )}
                  {!turn.complete && <span className="discourse-typing" />}
                </div>
              ))}
            </div>
            {discourseRunning && (
              <div className="chat-loading">
                <span className="chat-loading-dot" />
                Agents discussing...
              </div>
            )}
          </div>
        )}
        {running && !discourseRunning && (
          <div className="chat-entry chat-entry--loading">
            <span className="chat-loading-dot" />
            Working...
          </div>
        )}
      </div>

      <div className="chat-input-area">
        {showSlash && (filteredCommands.length > 0 || clearMatches) && (
          <div className="slash-menu">
            {filteredCommands.map((c) => (
              <button
                key={c.cmd}
                className="slash-item"
                onMouseDown={(e) => {
                  e.preventDefault();
                  selectSlashCommand(c);
                }}
              >
                <span className="slash-item__cmd">/{c.cmd}</span>
                <span className="slash-item__label">{c.label}</span>
              </button>
            ))}
            {clearMatches && (
              <button
                className="slash-item"
                onMouseDown={(e) => {
                  e.preventDefault();
                  handleClear();
                }}
              >
                <span className="slash-item__cmd">/clear</span>
                <span className="slash-item__label">Clear chat history</span>
              </button>
            )}
          </div>
        )}

        {showMention && filteredMentions.length > 0 && (
          <div className="slash-menu">
            {filteredMentions.map((m) => (
              <button
                key={m.name}
                className="slash-item"
                onMouseDown={(e) => {
                  e.preventDefault();
                  selectMention(m.name);
                }}
              >
                <span className="slash-item__cmd">@{m.name}</span>
                <span className="slash-item__label">{m.label}</span>
              </button>
            ))}
          </div>
        )}

        {showModes && (
          <div className="mode-expand">
            {MODES.map((m) => (
              <button
                key={m}
                className={`mode-expand__btn ${mode === m ? "mode-expand__btn--active" : ""}`}
                onClick={() => {
                  setMode(m);
                  setShowModes(false);
                  inputRef.current?.focus();
                }}
              >
                {SESSION_MODE_LABELS[m]}
              </button>
            ))}
          </div>
        )}

        <div className="chat-bar">
          <button
            className={`chat-plus ${showModes ? "chat-plus--open" : ""}`}
            onClick={() => setShowModes(!showModes)}
            title="Select mode"
          >
            +
          </button>
          {mode !== "general" && (
            <span
              className={`chat-mode-tag ${kickoffSuggested && mode !== "plan" ? "chat-mode-tag--suggested" : ""}`}
              onClick={() => {
                setMode("general");
              }}
              title="Click to clear mode"
            >
              {SESSION_MODE_LABELS[mode]}
            </span>
          )}
          <textarea
            ref={inputRef}
            className="chat-input"
            value={message}
            onChange={(e) => handleInputChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              mode === "general"
                ? "Message the workbench...  (/ for commands)"
                : `${SESSION_MODE_LABELS[mode]}...`
            }
            disabled={running || !projectId}
            rows={1}
          />
          <button
            className="chat-send"
            onClick={handleSend}
            disabled={running || !projectId || !message.trim()}
            title="Send (Enter)"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path
                d="M14 8L2 2L4 8L2 14L14 8Z"
                fill="currentColor"
              />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}

const AssistantMessage = memo(function AssistantMessage({
  result,
  speaker,
  modelRole,
  handoffs,
  task,
  plan,
  parsed,
  displayText,
}: {
  result: CommandResult;
  speaker: string;
  modelRole?: string;
  handoffs?: ChatHandoff[];
  task?: ChatTaskProposal | null;
  plan?: ChatPlanProposal | null;
  parsed?: ParsedSession;
  displayText?: string;
}) {
  const messageText =
    displayText ||
    (plan ? summarizePlan(plan) : "") ||
    (task ? summarizeTask(task) : "") ||
    parsed?.message_text ||
    parsed?.summary_text ||
    result.stdout ||
    result.stderr ||
    "No assistant text returned.";
  const footerBits = [
    parsed?.session_id && `Session ${parsed.session_id}`,
    parsed?.current_task && `Task ${parsed.current_task}`,
    parsed?.final_decision && `Decision ${parsed.final_decision}`,
    plan && summarizePlan(plan),
    task && summarizeTask(task),
  ].filter(Boolean);

  return (
    <>
      <div className="chat-message__identity">
        <div className="chat-message__speaker" style={{ color: speakerColor(speaker) }}>
          {speaker}
        </div>
        {modelRole && <div className="chat-message__role">{humanizeLabel(modelRole)}</div>}
      </div>
      <div className="chat-entry__text chat-markdown">
        <MarkdownMessage text={messageText} />
      </div>
      {footerBits.length > 0 && <div className="chat-message__footer">{footerBits.join(" • ")}</div>}
      {handoffs && handoffs.length > 0 && (
        <div className="chat-message__handoffs">
          {handoffs.map((handoff, i) => (
            <span key={i} className="chat-handoff">
              Ping {humanizeLabel(handoff.role)}
            </span>
          ))}
        </div>
      )}
      {(parsed?.human_questions?.length ?? 0) > 0 && (
        <div className="chat-questions">
          <span className="chat-questions__label">Questions:</span>
          {parsed?.human_questions?.map((q, i) => (
            <div key={i} className="chat-questions__item">- {q}</div>
          ))}
        </div>
      )}
      {parsed?.transition_blocked && (
        <div className="chat-blocked">Transition blocked</div>
      )}
      {result.stderr && (
        <div className="chat-stderr">{result.stderr}</div>
      )}
      {result.stdout && (
        <details className="chat-raw">
          <summary>Raw output</summary>
          <pre className="chat-raw__pre">{result.stdout}</pre>
        </details>
      )}
    </>
  );
});

const MarkdownMessage = memo(function MarkdownMessage({ text }: { text: string }) {
  const blocks = useMemo(() => parseMarkdownBlocks(text), [text]);
  return <>{blocks.map((block, i) => renderMarkdownBlock(block, i))}</>;
});

const CopyButton = memo(function CopyButton({
  text,
  label,
  className = "",
  disabled = false,
  title = "Copy",
}: {
  text: string;
  label?: string;
  className?: string;
  disabled?: boolean;
  title?: string;
}) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    if (disabled || !text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (_) { /* clipboard may not be available */ }
  };
  return (
    <button
      className={`${label ? "chat-header-copy" : "chat-copy"} ${copied ? (label ? "chat-header-copy--done" : "chat-copy--done") : ""} ${className}`.trim()}
      onClick={handleCopy}
      title={title}
      disabled={disabled || !text}
    >
      {copied ? "Copied" : label ?? (
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <rect x="5" y="5" width="9" height="9" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
          <path d="M11 5V3.5A1.5 1.5 0 009.5 2h-6A1.5 1.5 0 002 3.5v6A1.5 1.5 0 003.5 11H5" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      )}
    </button>
  );
});

type MarkdownBlock =
  | { type: "paragraph"; text: string }
  | { type: "heading"; level: 1 | 2 | 3; text: string }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "quote"; lines: string[] }
  | { type: "code"; language: string; code: string };

function parseMarkdownBlocks(text: string): MarkdownBlock[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: MarkdownBlock[] = [];
  let paragraph: string[] = [];
  let quote: string[] = [];
  let listItems: string[] = [];
  let listOrdered = false;
  let inCode = false;
  let codeLang = "";
  let codeLines: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length > 0) {
      blocks.push({ type: "paragraph", text: paragraph.join(" ").trim() });
      paragraph = [];
    }
  };

  const flushQuote = () => {
    if (quote.length > 0) {
      blocks.push({ type: "quote", lines: quote.slice() });
      quote = [];
    }
  };

  const flushList = () => {
    if (listItems.length > 0) {
      blocks.push({ type: "list", ordered: listOrdered, items: listItems.slice() });
      listItems = [];
    }
  };

  const flushCode = () => {
    if (inCode) {
      blocks.push({
        type: "code",
        language: codeLang,
        code: codeLines.join("\n"),
      });
      inCode = false;
      codeLang = "";
      codeLines = [];
    }
  };

  for (const line of lines) {
    const codeFence = line.match(/^```(\w+)?\s*$/);
    if (codeFence) {
      if (inCode) {
        flushCode();
      } else {
        flushParagraph();
        flushQuote();
        flushList();
        inCode = true;
        codeLang = codeFence[1] ?? "";
        codeLines = [];
      }
      continue;
    }

    if (inCode) {
      codeLines.push(line);
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      flushQuote();
      flushList();
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    if (heading) {
      flushParagraph();
      flushQuote();
      flushList();
      blocks.push({
        type: "heading",
        level: heading[1].length as 1 | 2 | 3,
        text: heading[2].trim(),
      });
      continue;
    }

    const quoteLine = line.match(/^>\s?(.*)$/);
    if (quoteLine) {
      flushParagraph();
      flushList();
      quote.push(quoteLine[1]);
      continue;
    }

    const orderedItem = line.match(/^\s*\d+\.\s+(.*)$/);
    if (orderedItem) {
      flushParagraph();
      flushQuote();
      listOrdered = true;
      listItems.push(orderedItem[1]);
      continue;
    }

    const bulletItem = line.match(/^\s*[-*+]\s+(.*)$/);
    if (bulletItem) {
      flushParagraph();
      flushQuote();
      listOrdered = false;
      listItems.push(bulletItem[1]);
      continue;
    }

    flushQuote();
    flushList();
    paragraph.push(line.trim());
  }

  flushParagraph();
  flushQuote();
  flushList();
  flushCode();

  return blocks.length > 0 ? blocks : [{ type: "paragraph", text }];
}

function renderMarkdownBlock(block: MarkdownBlock, key: number) {
  switch (block.type) {
    case "heading": {
      const Tag = block.level === 1 ? "h1" : block.level === 2 ? "h2" : "h3";
      return (
        <Tag key={key} className={`chat-md__heading chat-md__heading--${block.level}`}>
          {renderInlineMarkdown(block.text)}
        </Tag>
      );
    }
    case "list":
      return block.ordered ? (
        <ol key={key} className="chat-md__list">
          {block.items.map((item, index) => (
            <li key={index}>{renderInlineMarkdown(item)}</li>
          ))}
        </ol>
      ) : (
        <ul key={key} className="chat-md__list">
          {block.items.map((item, index) => (
            <li key={index}>{renderInlineMarkdown(item)}</li>
          ))}
        </ul>
      );
    case "quote":
      return (
        <blockquote key={key} className="chat-md__quote">
          {block.lines.map((line, index) => (
            <div key={index}>{renderInlineMarkdown(line)}</div>
          ))}
        </blockquote>
      );
    case "code":
      return (
        <pre key={key} className="chat-md__codeblock">
          <code className={block.language ? `language-${block.language}` : undefined}>
            {block.code}
          </code>
        </pre>
      );
    case "paragraph":
    default:
      return (
        <p key={key} className="chat-md__paragraph">
          {renderInlineMarkdown(block.text)}
        </p>
      );
  }
}

function renderInlineMarkdown(text: string): ReactNode[] {
  const tokens: ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\[[^\]]+\]\([^)]+\)|\*[^*]+\*|_[^_]+_)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      tokens.push(text.slice(lastIndex, match.index));
    }

    const token = match[0];
    if ((token.startsWith("**") && token.endsWith("**")) || (token.startsWith("__") && token.endsWith("__"))) {
      tokens.push(<strong key={`b-${key++}`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`") && token.endsWith("`")) {
      tokens.push(<code key={`c-${key++}`}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("[") && token.includes("](") && token.endsWith(")")) {
      const splitAt = token.indexOf("](");
      const label = token.slice(1, splitAt);
      const href = token.slice(splitAt + 2, -1);
      tokens.push(
        <a key={`a-${key++}`} href={href} target="_blank" rel="noreferrer">
          {label}
        </a>
      );
    } else if ((token.startsWith("*") && token.endsWith("*")) || (token.startsWith("_") && token.endsWith("_"))) {
      tokens.push(<em key={`i-${key++}`}>{token.slice(1, -1)}</em>);
    } else {
      tokens.push(token);
    }

    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) {
    tokens.push(text.slice(lastIndex));
  }

  return tokens;
}

interface ThreadNode extends ChatEntry {
  children: ThreadNode[];
}

function buildThreadRoots(entries: ChatEntry[]): ThreadNode[] {
  const nodes = new Map<number, ThreadNode>();
  const roots: ThreadNode[] = [];

  for (const entry of entries) {
    nodes.set(entry.id, { ...entry, children: [] });
  }

  for (const entry of entries) {
    const node = nodes.get(entry.id);
    if (!node) continue;
    const parentId = entry.replyToId;
    const parent = parentId != null ? nodes.get(parentId) : undefined;
    if (parent) {
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }

  return roots;
}

const ThreadNodeView = memo(function ThreadNodeView({ node, fallbackSpeaker, depth = 0 }: { node: ThreadNode; fallbackSpeaker: string; depth?: number }) {
  const nodeStyle = depth > 0 ? { marginLeft: `${depth * 20}px` } : undefined;

  return (
    <div key={node.id} className="chat-thread-node" style={nodeStyle}>
      <ChatEntryView entry={node} fallbackSpeaker={fallbackSpeaker} />
      {node.children.length > 0 && (
        <div className="chat-thread-children">
          {node.children.map((child) => <ThreadNodeView key={child.id} node={child} fallbackSpeaker={fallbackSpeaker} depth={depth + 1} />)}
        </div>
      )}
    </div>
  );
});

const ChatEntryView = memo(function ChatEntryView({ entry, fallbackSpeaker }: { entry: ChatEntry; fallbackSpeaker: string }) {
  if (entry.role === "human") {
    return (
      <div className="chat-entry chat-entry--human">
        <CopyButton text={entry.content} />
        {entry.mode && entry.mode !== "general" && (
          <span className="chat-entry__mode">
            {SESSION_MODE_LABELS[entry.mode!]}
          </span>
        )}
        <div className="chat-entry__text">{entry.content}</div>
      </div>
    );
  }

  if (entry.role === "assistant" && entry.result) {
    const messageText =
      entry.displayText ||
      resolveAssistantText({
        stdout: entry.result.stdout,
        stderr: entry.result.stderr,
        parsedText:
          entry.task
            ? summarizeTask(entry.task)
            : entry.parsed?.message_text,
        parsedSummary: entry.parsed?.summary_text,
        taskSummary: entry.task ? summarizeTask(entry.task) : "",
      });
    return (
      <div className="chat-entry chat-entry--assistant">
        <CopyButton text={messageText} />
        <AssistantMessage
          result={entry.result}
          speaker={entry.speaker ?? fallbackSpeaker}
          modelRole={entry.modelRole}
          handoffs={entry.handoffs}
          task={entry.task}
          plan={entry.plan}
          parsed={entry.parsed}
          displayText={entry.displayText}
        />
      </div>
    );
  }

  return (
    <div className="chat-entry chat-entry--error">
      {entry.content}
    </div>
  );
});

function buildRoleTargets(routing: RoutingConfig | null) {
  if (!routing) return {} as Record<string, { nickname: string; displayName: string; roleLabel: string }>;

  const byModelRef = new Map(routing.models.map((model) => [model.model_ref, model]));
  return routing.roles.reduce<Record<string, { nickname: string; displayName: string; roleLabel: string }>>((acc, role) => {
    const model = byModelRef.get(role.model_ref);
    const nickname = model?.nickname ?? role.role;
    acc[role.role] = {
      nickname,
      displayName: nickname,
      roleLabel: humanizeLabel(role.role),
    };
    return acc;
  }, {});
}

function normalizeHistory(
  entries: ChatEntry[],
  roleTargets: Record<string, { nickname: string; displayName: string; roleLabel: string }>
): ChatEntry[] {
  const speakerToRole = new Map<string, string>();
  for (const [role, target] of Object.entries(roleTargets)) {
    speakerToRole.set(role.toLowerCase(), role);
    speakerToRole.set(target.displayName.toLowerCase(), role);
    speakerToRole.set(target.nickname.toLowerCase(), role);
  }

  return entries.map((entry) => {
    if (entry.role !== "assistant") return entry;
    const normalized: ChatEntry = { ...entry };
    const inferredRole =
      normalized.modelRole ??
      (normalized.speaker ? speakerToRole.get(normalized.speaker.toLowerCase()) : undefined);

    if (inferredRole) {
      normalized.modelRole = inferredRole;
      normalized.speaker = roleTargets[inferredRole]?.displayName ?? inferredRole;
      return normalized;
    }

    if (normalized.speaker) {
      const directRole = speakerToRole.get(normalized.speaker.toLowerCase());
      if (directRole) {
        normalized.modelRole = directRole;
        normalized.speaker = roleTargets[directRole]?.displayName ?? directRole;
        return normalized;
      }
    }

    if (!normalized.speaker || normalized.speaker === "Workbench") {
      normalized.speaker = "Unknown model";
    }

    return normalized;
  });
}

function buildRelayPrompt({
  fromRole,
  fromSpeaker,
  toRole,
  originalMessage,
  replyText,
  reason,
}: {
  fromRole: string;
  fromSpeaker: string;
  toRole: string;
  originalMessage: string;
  replyText: string;
  reason: string;
}) {
  return [
    `[Relay from ${fromSpeaker} (${humanizeLabel(fromRole)}) to ${humanizeLabel(toRole)}]`,
    "",
    "Original request:",
    originalMessage,
    "",
    "Previous reply:",
    replyText,
    "",
    "Reason for handoff:",
    reason,
    "",
    `Please respond as ${humanizeLabel(toRole)}. Keep it short, use natural Markdown, open with a short answer, and only add a Details section if useful.`,
  ].join("\n");
}

function buildChatContext(history: ChatEntry[]): string {
  const seen = new Set<string>();
  for (const entry of history) {
    if (entry.role !== "assistant" || !entry.speaker) continue;
    const speaker = entry.speaker.trim();
    if (speaker) {
      seen.add(speaker);
    }
  }

  if (seen.size === 0) {
    return "";
  }

  return [
    "Thread memory:",
    `Already introduced in this conversation: ${Array.from(seen).join(", ")}.`,
    "Do not repeat introductions for those speakers unless the operator explicitly asks for an introduction.",
    "Keep later replies natural and direct.",
  ].join(" ");
}

function buildChatSessionSummary({
  history,
  projectId,
  responseMode,
  autoRelay,
  running,
}: {
  history: ChatEntry[];
  projectId: string | null;
  responseMode: ResponseMode;
  autoRelay: boolean;
  running: boolean;
}): ChatSessionSummary | null {
  if (!projectId) return null;

  const visibleHistory = history.filter((entry) => entry.role !== "status");
  if (visibleHistory.length === 0) return null;

  const latestTurn = visibleHistory[visibleHistory.length - 1];
  const latestAssistant = [...visibleHistory].reverse().find((entry) => entry.role === "assistant");
  const latestHuman = [...visibleHistory].reverse().find((entry) => entry.role === "human");
  const latestText = latestAssistant
    ? resolveAssistantText({
        stdout: latestAssistant.result?.stdout ?? "",
        stderr: latestAssistant.result?.stderr ?? "",
        parsedText:
          latestAssistant.displayText ||
          (latestAssistant.task ? summarizeTask(latestAssistant.task) : latestAssistant.parsed?.message_text),
        parsedSummary: latestAssistant.parsed?.summary_text,
        taskSummary: latestAssistant.task ? summarizeTask(latestAssistant.task) : "",
      })
    : latestHuman?.content ?? "";

  const preview = latestText.replace(/\s+/g, " ").trim();
  const currentSpeaker =
    latestTurn.role === "human"
      ? "You"
      : latestAssistant?.speaker ?? "Workbench";
  const currentRole =
    latestTurn.role === "human"
      ? "Operator"
      : latestAssistant?.modelRole
        ? humanizeLabel(latestAssistant.modelRole)
        : "Workbench";
  const state = running
    ? "responding"
    : latestTurn.role === "human"
      ? "waiting"
      : "active";

  return {
    project_id: projectId,
    current_speaker: currentSpeaker,
    current_role: currentRole,
    response_mode: responseMode,
    relay_enabled: autoRelay,
    turn_count: visibleHistory.length,
    preview: preview || "Awaiting reply",
    state,
  };
}

function buildChatTranscript(entries: ThreadNode[], projectId: string | null): string {
  if (entries.length === 0) {
    return "";
  }

  const lines: string[] = [];

  if (projectId) {
    lines.push(`Project: ${projectId}`);
    lines.push("");
  }

  for (const entry of entries) {
    appendTranscriptNode(lines, entry, 0);
  }

  return lines.join("\n").trim();
}

function appendTranscriptNode(lines: string[], entry: ThreadNode, depth: number) {
  const speaker = transcriptSpeaker(entry);
  const content = transcriptContent(entry).trim();
  const indent = "  ".repeat(depth);

  if (lines.length > 0) {
    lines.push("");
  }

  if (content) {
    const contentLines = content.replace(/\r\n/g, "\n").split("\n");
    lines.push(`${indent}${speaker}: ${contentLines[0]}`);
    for (const extra of contentLines.slice(1)) {
      lines.push(`${indent}  ${extra}`);
    }
  } else {
    lines.push(`${indent}${speaker}:`);
  }

  for (const child of entry.children) {
    appendTranscriptNode(lines, child, depth + 1);
  }
}

function transcriptSpeaker(entry: ThreadNode): string {
  if (entry.role === "human") {
    return "You";
  }
  if (entry.role === "assistant") {
    const speaker = entry.speaker ?? "Workbench";
    const role = entry.modelRole ? ` (${humanizeLabel(entry.modelRole)})` : "";
    return `${speaker}${role}`;
  }
  return "System";
}

function transcriptContent(entry: ThreadNode): string {
  if (entry.role === "assistant") {
    return (
      entry.displayText ||
      resolveAssistantText({
        stdout: entry.result?.stdout ?? "",
        stderr: entry.result?.stderr ?? "",
        parsedText:
          entry.task
            ? summarizeTask(entry.task)
            : entry.parsed?.message_text,
        parsedSummary: entry.parsed?.summary_text,
        taskSummary: entry.task ? summarizeTask(entry.task) : "",
      })
    );
  }
  return entry.content;
}

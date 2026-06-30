export interface ChatHandoff {
  role: string;
  reason: string;
}

export interface ChatTaskProposal {
  title: string;
  goal: string;
  taskType: string;
  acceptance: string[];
  scope: string[];
}

export interface ChatPlanProposal {
  title: string;
  summary: string;
  tasks: ChatTaskProposal[];
}

export interface ParsedChatReply {
  text: string;
  handoffs: ChatHandoff[];
  task: ChatTaskProposal | null;
  plan: ChatPlanProposal | null;
}

export function parseChatReply(stdout: string): ParsedChatReply {
  const lines = stdout.split("\n");
  const hasPlanMarker = lines.some((line) => isPlanMarker(line.trim()));
  const taskMarkerCount = lines.reduce(
    (count, line) => count + (isTaskMarker(line.trim()) ? 1 : 0),
    0
  );
  const planMode = hasPlanMarker || taskMarkerCount > 1;

  const bodyLines: string[] = [];
  const handoffs: ChatHandoff[] = [];
  const taskLines: string[] = [];
  const planHeaderLines: string[] = [];
  const planTaskBlocks: string[][] = [];
  let inHandoff = false;
  let inTask = false;
  let inPlan = false;
  let planTaskStarted = false;
  let currentPlanTask: string[] = [];

  for (const line of lines) {
    const trimmed = line.trimEnd();
    const compact = trimmed.trim();

    if (!inPlan && planMode) {
      const isPlanStart = hasPlanMarker ? isPlanMarker(compact) : isTaskMarker(compact);
      if (isPlanStart) {
        inPlan = true;
        if (!hasPlanMarker && isTaskMarker(compact)) {
          planTaskStarted = true;
        }
        continue;
      }
    }

    if (!inPlan && !inTask && !inHandoff && isTaskMarker(compact)) {
      inTask = true;
      continue;
    }

    if (!inPlan && !inTask && isHandoffMarker(compact)) {
      inHandoff = true;
      continue;
    }

    if (inPlan) {
      if (isHandoffMarker(compact)) {
        inPlan = false;
        inHandoff = true;
        if (currentPlanTask.length > 0) {
          planTaskBlocks.push(currentPlanTask);
          currentPlanTask = [];
        }
        continue;
      }

      if (isTaskMarker(compact)) {
        if (currentPlanTask.length > 0) {
          planTaskBlocks.push(currentPlanTask);
          currentPlanTask = [];
        }
        planTaskStarted = true;
        continue;
      }

      if (planTaskStarted || planTaskBlocks.length > 0 || currentPlanTask.length > 0) {
        currentPlanTask.push(line);
      } else {
        planHeaderLines.push(line);
      }
      continue;
    }

    if (inTask) {
      if (isHandoffMarker(compact)) {
        inTask = false;
        inHandoff = true;
        continue;
      }
      taskLines.push(line);
      continue;
    }

    if (inHandoff) {
      if (compact === "") {
        continue;
      }

      if (isTaskMarker(compact)) {
        inHandoff = false;
        inTask = true;
        continue;
      }

      const match = compact.match(/^(?:[-*]\s*)?@?([a-z0-9_-]+)\s*[:\-]\s*(.+)$/i);
      if (match) {
        handoffs.push({
          role: match[1].toLowerCase(),
          reason: match[2].trim(),
        });
        continue;
      }

      inHandoff = false;
    }

    bodyLines.push(trimmed);
  }

  if (currentPlanTask.length > 0) {
    planTaskBlocks.push(currentPlanTask);
  }

  const plan = planMode ? parsePlanProposal(planHeaderLines, planTaskBlocks) : null;
  const task = parseTaskProposal(taskLines) || plan?.tasks?.[0] || null;

  return {
    text: compactText(bodyLines.join("\n")),
    handoffs,
    task,
    plan,
  };
}

function isTaskMarker(line: string): boolean {
  return /^(task(?:\s+\d+)?(?:\s+proposal)?):?\s*$/i.test(line);
}

function isPlanMarker(line: string): boolean {
  return /^plan(?:\s+proposal)?\s*:?\s*$/i.test(line);
}

function isHandoffMarker(line: string): boolean {
  return /^handoff:?\s*$/i.test(line);
}

function parsePlanProposal(
  headerLines: string[],
  taskBlocks: string[][]
): ChatPlanProposal | null {
  if (taskBlocks.length === 0) return null;

  const proposal: ChatPlanProposal = {
    title: "",
    summary: "",
    tasks: [],
  };

  parsePlanHeader(headerLines, proposal);

  for (const block of taskBlocks) {
    const task = parseTaskProposal(block);
    if (task) {
      proposal.tasks.push(task);
    }
  }

  if (proposal.tasks.length === 0) return null;
  if (!proposal.title && proposal.tasks[0].title) {
    proposal.title = proposal.tasks[0].title;
  }

  return proposal;
}

function parsePlanHeader(lines: string[], proposal: ChatPlanProposal): void {
  let sawContent = false;
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;

    const keyMatch = line.match(/^[-*]?\s*([A-Za-z0-9 _-]+?)\s*:\s*(.*)$/);
    if (keyMatch) {
      const key = keyMatch[1].trim().toLowerCase().replace(/\s+/g, "_");
      const value = keyMatch[2].trim();
      sawContent = true;

      if (key === "title" || key === "plan_title" || key === "name") {
        proposal.title = value;
      } else if (key === "summary" || key === "objective" || key === "overview") {
        proposal.summary = value;
      } else if (!proposal.title && value) {
        proposal.title = value;
      } else if (!proposal.summary && value) {
        proposal.summary = value;
      }
      continue;
    }

    if (!proposal.title) {
      proposal.title = line;
      sawContent = true;
      continue;
    }

    if (!proposal.summary) {
      proposal.summary = line;
      sawContent = true;
    }
  }

  if (!sawContent) {
    return;
  }
}

function parseTaskProposal(lines: string[]): ChatTaskProposal | null {
  if (lines.length === 0) return null;

  const proposal: ChatTaskProposal = {
    title: "",
    goal: "",
    taskType: "implementation",
    acceptance: [],
    scope: [],
  };
  let currentList: "acceptance" | "scope" | null = null;
  let sawContent = false;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;

    const keyMatch = line.match(/^[-*]?\s*([A-Za-z0-9 _-]+?)\s*:\s*(.*)$/);
    if (keyMatch) {
      const key = keyMatch[1].trim().toLowerCase().replace(/\s+/g, "_");
      const value = keyMatch[2].trim();
      sawContent = true;
      currentList = null;

      if (key === "type" || key === "task_type") {
        proposal.taskType = value || proposal.taskType;
      } else if (key === "title") {
        proposal.title = value;
      } else if (key === "goal" || key === "objective" || key === "summary") {
        proposal.goal = value;
      } else if (key === "acceptance") {
        currentList = "acceptance";
        if (value) proposal.acceptance.push(value);
      } else if (key === "scope") {
        currentList = "scope";
        if (value) proposal.scope.push(value);
      } else if (!proposal.goal && value) {
        proposal.goal = value;
      }
      continue;
    }

    const bulletMatch = line.match(/^[-*]\s+(.*)$/);
    if (bulletMatch && currentList) {
      sawContent = true;
      proposal[currentList].push(bulletMatch[1].trim());
      continue;
    }

    if (!proposal.title) {
      proposal.title = line;
      sawContent = true;
      continue;
    }

    if (!proposal.goal) {
      proposal.goal = line;
      sawContent = true;
    }
  }

  if (!sawContent) return null;
  if (!proposal.goal) proposal.goal = proposal.title;

  return proposal;
}

function compactText(text: string): string {
  return text
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]+\n/g, "\n")
    .trim();
}

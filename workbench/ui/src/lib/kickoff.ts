const PLAN_KICKOFF_CUES = [
  "plan kickoff",
  "kick off the plan",
  "kickoff the plan",
  "kickoff",
  "implementation plan",
  "work from the plan",
  "start from the plan",
  "read the plan",
  "feature brief",
  "current-state",
  "current state",
  "plan is available",
  "plan available",
  "roadmap",
];

export function looksLikePlanKickoff(text: string): boolean {
  const normalized = text.toLowerCase().replace(/\s+/g, " ").trim();
  if (!normalized) return false;
  return PLAN_KICKOFF_CUES.some((cue) => normalized.includes(cue));
}

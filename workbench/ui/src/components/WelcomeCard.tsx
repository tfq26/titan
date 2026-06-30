import type { ProjectEntry } from "../types";

interface Props {
  project: ProjectEntry | null;
  onSelectProject?: () => void;
}

export function WelcomeCard({ project, onSelectProject }: Props) {
  return (
    <div className="welcome-card">
      <div className="welcome-card__icon">⚡</div>
      <div className="welcome-card__title">Welcome to Workbench</div>
      <div className="welcome-card__subtitle">
        A multi-agent engineering environment where AI agents collaborate on
        your projects. Select a project and start a conversation.
      </div>
      <div className="welcome-card__steps">
        <div className="welcome-step">
          <div className="welcome-step__num">1</div>
          <div className="welcome-step__content">
            <div className="welcome-step__heading">Select a project</div>
            <div className="welcome-step__desc">
              {project
                ? `Currently selected: ${project.name}`
                : "Choose a project from the sidebar to get started."}
              {!project && onSelectProject && (
                <>
                  {" "}
                  <button className="btn btn--sm btn--primary" onClick={onSelectProject}>
                    Select project
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
        <div className="welcome-step">
          <div className="welcome-step__num">2</div>
          <div className="welcome-step__content">
            <div className="welcome-step__heading">Send a message</div>
            <div className="welcome-step__desc">
              Type your request — the workbench agents will process it
              and return results. Use <code>/</code> for slash commands.
            </div>
          </div>
        </div>
        <div className="welcome-step">
          <div className="welcome-step__num">3</div>
          <div className="welcome-step__content">
            <div className="welcome-step__heading">Track tasks</div>
            <div className="welcome-step__desc">
              Switch to the <strong>Queue</strong> tab to see task progress.
              Configure models in the <strong>Configure</strong> tab.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

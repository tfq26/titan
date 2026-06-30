import { useMemo, useState } from "react";
import type { ProjectEntry } from "../types";
import type { ProjectAddInput } from "../types";
import { StatusBadge } from "../components/StatusBadge";
import { pickFolder } from "../bridge/system";

interface Props {
  projects: ProjectEntry[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onAddProject: (project: ProjectAddInput) => Promise<ProjectEntry>;
}

export function ProjectSelector({
  projects,
  selectedId,
  onSelect,
  onAddProject,
}: Props) {
  const [showAdd, setShowAdd] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const [repoRoot, setRepoRoot] = useState("");
  const [vaultRoot, setVaultRoot] = useState("");
  const [reportRoot, setReportRoot] = useState("");
  const [status, setStatus] = useState("registered");
  const [note, setNote] = useState("");
  const [pickingFolder, setPickingFolder] = useState(false);

  const derivedDefaults = useMemo(() => {
    const cleanedRepo = repoRoot.trim().replace(/\/+$/, "");
    const repoName = cleanedRepo.split("/").filter(Boolean).slice(-1)[0] ?? "";
    const derivedName = name.trim() || repoName;
    const derivedId = slugify(projectId.trim() || derivedName || repoName);
    const derivedVault = vaultRoot.trim() || (cleanedRepo ? `${cleanedRepo}/docs/vault` : "");
    const derivedReport =
      reportRoot.trim() || (cleanedRepo ? `${cleanedRepo}/docs/reports/subagents` : "");
    return {
      derivedName,
      derivedId,
      derivedVault,
      derivedReport,
    };
  }, [name, projectId, reportRoot, repoRoot, vaultRoot]);

  const openAdd = () => {
    setProjectId("");
    setName("");
    setRepoRoot("");
    setVaultRoot("");
    setReportRoot("");
    setStatus("registered");
    setNote("");
    setError("");
    setShowAdd(true);
  };

  const chooseRepoRoot = async () => {
    setError("");
    setPickingFolder(true);
    try {
      const picked = await pickFolder();
      if (!picked) {
        return;
      }
      const cleanedRepo = picked.trim().replace(/\/+$/, "");
      const repoName = cleanedRepo.split("/").filter(Boolean).slice(-1)[0] ?? "";
      setRepoRoot(cleanedRepo);
      setName((current) => current.trim() || repoName);
      setProjectId((current) => current.trim() || slugify(repoName));
      setVaultRoot((current) => current.trim() || (cleanedRepo ? `${cleanedRepo}/docs/vault` : ""));
      setReportRoot(
        (current) => current.trim() || (cleanedRepo ? `${cleanedRepo}/docs/reports/subagents` : "")
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setPickingFolder(false);
    }
  };

  const submitAdd = async () => {
    const cleanedRepo = repoRoot.trim();
    if (!cleanedRepo) {
      setError("Repo root is required.");
      return;
    }

    const payload: ProjectAddInput = {
      project_id: derivedDefaults.derivedId,
      name: derivedDefaults.derivedName || derivedDefaults.derivedId,
      repo_root: cleanedRepo,
      vault_root: derivedDefaults.derivedVault,
      report_root: derivedDefaults.derivedReport,
      status: status.trim() || "registered",
      created: new Date().toISOString().slice(0, 10),
      note: note.trim() || undefined,
    };

    setSaving(true);
    setError("");
    try {
      await onAddProject(payload);
      setShowAdd(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="panel project-selector">
      <div className="project-selector__header">
        <h3 className="panel__title">Projects</h3>
        <button
          type="button"
          className="project-add-btn"
          onClick={openAdd}
          title="Add project"
        >
          +
        </button>
      </div>
      <ul className="project-list">
        {projects.map((p) => (
          <li
            key={p.id}
            className={`project-item ${p.id === selectedId ? "project-item--selected" : ""}`}
            onClick={() => onSelect(p.id)}
          >
            <div className="project-item__name">{p.name}</div>
            <StatusBadge status={p.status} />
            <div className="project-item__paths">
              <span className="mono-sm" title={p.repo_root}>
                {p.repo_root.split("/").slice(-2).join("/")}
              </span>
            </div>
          </li>
        ))}
      </ul>
      {showAdd && (
        <div className="project-add-modal" role="dialog" aria-modal="true">
          <div className="project-add-modal__card">
            <div className="project-add-modal__header">
              <div>
                <div className="project-add-modal__title">Add Project</div>
                <div className="project-add-modal__subtitle">
                  Register a repo and boot its shared workbench config.
                </div>
              </div>
              <button
                type="button"
                className="project-add-modal__close"
                onClick={() => setShowAdd(false)}
                aria-label="Close"
              >
                ×
              </button>
            </div>

            <div className="project-add-form">
              <div className="project-add-field project-add-field--wide">
                <span className="project-add-field__label">Project Folder</span>
                <div className="project-add-picker">
                  <div className="project-add-picker__path mono-sm" title={repoRoot || "No folder selected yet"}>
                    {repoRoot || "No folder selected yet"}
                  </div>
                  <button
                    type="button"
                    className="btn"
                    onClick={chooseRepoRoot}
                    disabled={pickingFolder}
                  >
                    {pickingFolder ? "Opening..." : repoRoot ? "Choose Different Folder" : "Choose Folder"}
                  </button>
                </div>
                <div className="project-add-picker__hint">
                  Select the repo folder in the native file picker. The vault and report paths will be derived from it.
                </div>
              </div>
              <label className="project-add-field">
                <span className="project-add-field__label">Name</span>
                <input
                  className="form-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={derivedDefaults.derivedName || "My Project"}
                />
              </label>
              <label className="project-add-field">
                <span className="project-add-field__label">Project ID</span>
                <input
                  className="form-input"
                  value={projectId}
                  onChange={(e) => setProjectId(e.target.value)}
                  placeholder={derivedDefaults.derivedId || "my-project"}
                />
              </label>
              <label className="project-add-field">
                <span className="project-add-field__label">Vault Root</span>
                <input
                  className="form-input"
                  value={vaultRoot}
                  onChange={(e) => setVaultRoot(e.target.value)}
                  placeholder={derivedDefaults.derivedVault || "/path/to/repo/docs/vault"}
                />
              </label>
              <label className="project-add-field">
                <span className="project-add-field__label">Report Root</span>
                <input
                  className="form-input"
                  value={reportRoot}
                  onChange={(e) => setReportRoot(e.target.value)}
                  placeholder={derivedDefaults.derivedReport || "/path/to/repo/docs/reports/subagents"}
                />
              </label>
              <label className="project-add-field">
                <span className="project-add-field__label">Status</span>
                <select
                  className="form-input"
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                >
                  <option value="registered">registered</option>
                  <option value="active">active</option>
                </select>
              </label>
              <label className="project-add-field project-add-field--wide">
                <span className="project-add-field__label">Note</span>
                <textarea
                  className="form-textarea"
                  rows={3}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Optional bootstrap note or setup reminder"
                />
              </label>
              {error && <div className="project-add-error">{error}</div>}
              <div className="project-add-actions">
                <button
                  type="button"
                  className="btn"
                  onClick={() => setShowAdd(false)}
                  disabled={saving}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn btn--primary"
                  onClick={submitAdd}
                  disabled={saving || !repoRoot.trim()}
                >
                  {saving ? "Adding..." : "Add Project"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function slugify(value: string) {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

import { useState, useCallback, useEffect, useRef } from "react";
import type {
  RoutingConfig,
  EnvVarStatus,
  ProjectConfig,
  ModelConfig,
  ProjectModelPolicy,
  ModelEntry,
} from "../types";
import { PROVIDERS, ROLES, emptyModelConfig, modelEntryToConfig } from "../types";
import {
  addModel,
  updateModel,
  removeModel,
  updateRoleAssignment,
  updateProjectModelPolicy,
} from "../bridge/models";
import { checkSecretsFile, loadSecretsFile } from "../bridge/system";

interface Props {
  routing: RoutingConfig | null;
  envStatus: EnvVarStatus[];
  projectConfig: ProjectConfig | null;
  selectedProjectId: string | null;
  onRefreshRouting: () => void;
  onRefreshProjectConfig: () => void;
}

export function ModelPolicy({
  routing,
  envStatus,
  projectConfig,
  selectedProjectId,
  onRefreshRouting,
  onRefreshProjectConfig,
}: Props) {
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState<ModelConfig>(emptyModelConfig());
  const [newRef, setNewRef] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const [secretsFile, setSecretsFile] = useState<{ path: string; exists: boolean } | null>(null);
  const secretsLoadedRef = useRef(false);

  useEffect(() => {
    const poll = async () => {
      const status = await checkSecretsFile().catch(() => null);
      if (status) {
        setSecretsFile(status);
        if (status.exists && !secretsLoadedRef.current) {
          await loadSecretsFile().catch(() => {});
          onRefreshRouting();
          secretsLoadedRef.current = true;
        } else if (!status.exists) {
          secretsLoadedRef.current = false;
        }
      }
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, [onRefreshRouting]);

  const envMap = new Map(envStatus.map((e) => [e.name, e]));

  const policy = projectConfig?.model_policy as ProjectModelPolicy | undefined;
  const allowedRoles: Record<string, string[]> =
    (policy?.allowed_roles as Record<string, string[]>) ?? {};
  const deniedRefs: string[] = (policy?.denied_model_refs as string[]) ?? [];

  const refreshAll = useCallback(async () => {
    onRefreshRouting();
    onRefreshProjectConfig();
  }, [onRefreshRouting, onRefreshProjectConfig]);

  const clearEdit = () => {
    setEditing(null);
    setAdding(false);
    setForm(emptyModelConfig());
    setNewRef("");
    setError(null);
  };

  const handleAdd = async () => {
    if (!newRef.trim()) { setError("model_ref is required"); return; }
    setSaving(true);
    setError(null);
    try {
      await addModel(newRef.trim(), form);
      clearEdit();
      await refreshAll();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleUpdate = async () => {
    if (!editing) return;
    setSaving(true);
    setError(null);
    try {
      await updateModel(editing, form);
      clearEdit();
      await refreshAll();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleRemove = async (ref: string) => {
    setSaving(true);
    setError(null);
    try {
      await removeModel(ref);
      setConfirmRemove(null);
      await refreshAll();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleRoleChange = async (role: string, modelRef: string) => {
    setSaving(true);
    setError(null);
    try {
      await updateRoleAssignment(role, modelRef);
      await refreshAll();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleTogglePermission = async (role: string, modelRef: string, allowed: boolean) => {
    if (!selectedProjectId || !policy) return;
    const current = { ...allowedRoles };
    const list = [...(current[role] ?? [])];
    if (allowed && !list.includes(modelRef)) {
      list.push(modelRef);
    } else if (!allowed) {
      const idx = list.indexOf(modelRef);
      if (idx >= 0) list.splice(idx, 1);
    }
    current[role] = list;

    const updated: ProjectModelPolicy = {
      allowed_roles: current,
      denied_model_refs: deniedRefs,
      role_requirements: policy.role_requirements as Record<string, Record<string, unknown>> | undefined,
    };

    setSaving(true);
    setError(null);
    try {
      await updateProjectModelPolicy(selectedProjectId, updated);
      await refreshAll();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  if (!routing) return <div className="panel">Loading routing...</div>;

  const modelCount = routing.models.length;
  const envMissing = routing.models.filter(
    (m) => !m.env_vars.every((v) => envMap.get(v)?.present === true)
  ).length;
  const envInFile = routing.models.filter(
    (m) =>
      !m.env_vars.every((v) => envMap.get(v)?.present === true) &&
      m.env_vars.every((v) => {
        const s = envMap.get(v);
        return s?.present || s?.in_file;
      })
  ).length;
  const rolesAssigned = routing.roles.filter((r) =>
    routing.models.some((m) => m.model_ref === r.model_ref)
  ).length;
  const danglingRoles = routing.roles.filter(
    (r) => !routing.models.some((m) => m.model_ref === r.model_ref)
  );

  return (
    <div className="panel model-mgmt">
      {error && <div className="mgmt-error">{error}</div>}

      {secretsFile && !secretsFile.exists && (
        <div className="mgmt-warn">
          <strong>Secrets file not found</strong>
          <span>
            Expected at <code>{secretsFile.path}</code>
          </span>
          <span>
            Create this file with your API keys, then <code>source</code> it
            before launching the app. Model env vars will show as missing until
            the file is loaded into your shell environment.
          </span>
        </div>
      )}

      <section className="mgmt-section">
        <div className="mgmt-section__header">Status</div>
        <div className="mgmt-summary">
          <SummaryItem ok={modelCount > 0} text={`${modelCount} model(s) configured`} />
          <SummaryItem
            ok={envMissing === 0}
            warn={envMissing > 0 && envInFile > 0}
            text={
              envMissing === 0
                ? "All env vars present"
                : envInFile > 0
                  ? `${envInFile} model(s) have keys in secrets file but not loaded — restart app after sourcing`
                  : `${envMissing} model(s) missing env vars`
            }
          />
          <SummaryItem ok={danglingRoles.length === 0} text={danglingRoles.length === 0 ? `${rolesAssigned} role(s) assigned` : `${danglingRoles.length} role(s) point to missing model`} />
        </div>
      </section>

      <section className="mgmt-section">
        <div className="mgmt-section__header">
          Model Registry
          {!adding && !editing && (
            <button
              className="btn btn--sm"
              onClick={() => {
                setAdding(true);
                setEditing(null);
                setForm(emptyModelConfig());
                setNewRef("");
                setError(null);
              }}
            >
              + Add Model
            </button>
          )}
        </div>

        {adding && (
          <div className="model-form">
            <div className="model-form__field">
              <label className="form-label">model_ref</label>
              <input
                className="form-input"
                value={newRef}
                onChange={(e) => setNewRef(e.target.value)}
                placeholder="e.g. my_worker_model"
              />
            </div>
            <ModelFormFields form={form} setForm={setForm} />
            <div className="model-form__actions">
              <button className="btn btn--primary" onClick={handleAdd} disabled={saving}>
                {saving ? "Saving..." : "Add Model"}
              </button>
              <button className="btn" onClick={clearEdit}>Cancel</button>
            </div>
          </div>
        )}

        {routing.models.map((m) =>
          editing === m.model_ref ? (
            <div key={m.model_ref} className="model-form">
              <div className="model-form__ref">{m.model_ref}</div>
              <ModelFormFields form={form} setForm={setForm} />
              <div className="model-form__actions">
                <button className="btn btn--primary" onClick={handleUpdate} disabled={saving}>
                  {saving ? "Saving..." : "Save"}
                </button>
                <button className="btn" onClick={clearEdit}>Cancel</button>
              </div>
            </div>
          ) : (
            <ModelRow
              key={m.model_ref}
              model={m}
              envMap={envMap}
              isConfirmingRemove={confirmRemove === m.model_ref}
              onEdit={() => {
                setEditing(m.model_ref);
                setAdding(false);
                setForm(modelEntryToConfig(m));
                setError(null);
              }}
              onRemove={() => setConfirmRemove(m.model_ref)}
              onConfirmRemove={() => handleRemove(m.model_ref)}
              onCancelRemove={() => setConfirmRemove(null)}
            />
          )
        )}
      </section>

      <section className="mgmt-section">
        <div className="mgmt-section__header">Role Assignments</div>
        <div className="role-list">
          {ROLES.map((role) => {
            const current = routing.roles.find((r) => r.role === role);
            const currentRef = current?.model_ref ?? "";
            const valid = routing.models.some((m) => m.model_ref === currentRef);
            return (
              <div key={role} className="role-row">
                <span className="role-row__name">{role}</span>
                <select
                  className="form-select"
                  value={currentRef}
                  onChange={(e) => handleRoleChange(role, e.target.value)}
                  disabled={saving}
                >
                  {!valid && currentRef && (
                    <option value={currentRef}>{currentRef} (missing)</option>
                  )}
                  {routing.models.map((m) => (
                    <option key={m.model_ref} value={m.model_ref}>
                      {m.nickname || m.model_ref}
                    </option>
                  ))}
                </select>
                <span className={`status-dot ${valid ? "status-dot--ok" : "status-dot--missing"}`} />
              </div>
            );
          })}
        </div>
      </section>

      {selectedProjectId && (
        <section className="mgmt-section">
          <div className="mgmt-section__header">
            Project Permissions
            <span className="mgmt-section__sub">{selectedProjectId}</span>
          </div>
          {ROLES.map((role) => {
            const allowed = allowedRoles[role] ?? [];
            return (
              <div key={role} className="perm-row">
                <span className="perm-row__role">{role}</span>
                <div className="perm-row__models">
                  {routing.models.map((m) => {
                    const checked = allowed.includes(m.model_ref);
                    return (
                      <label key={m.model_ref} className="perm-check">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() =>
                            handleTogglePermission(role, m.model_ref, !checked)
                          }
                          disabled={saving}
                        />
                        <span className="perm-check__label">{m.nickname || m.model_ref}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
            );
          })}
          {deniedRefs.length > 0 && (
            <div className="perm-denied">
              <span className="form-label">Denied refs:</span>{" "}
              {deniedRefs.join(", ")}
            </div>
          )}
        </section>
      )}

      <div className="model-policy__note">
        Env var presence only. Secret values are never shown.
      </div>
    </div>
  );
}

function SummaryItem({ ok, warn, text }: { ok: boolean; warn?: boolean; text: string }) {
  const cls = ok ? "status-dot--ok" : warn ? "status-dot--warn" : "status-dot--missing";
  return (
    <div className="summary-item">
      <span className={`status-dot ${cls}`} />
      {text}
    </div>
  );
}

function ModelRow({
  model,
  envMap,
  isConfirmingRemove,
  onEdit,
  onRemove,
  onConfirmRemove,
  onCancelRemove,
}: {
  model: ModelEntry;
  envMap: Map<string, EnvVarStatus>;
  isConfirmingRemove: boolean;
  onEdit: () => void;
  onRemove: () => void;
  onConfirmRemove: () => void;
  onCancelRemove: () => void;
}) {
  const allPresent = model.env_vars.every((v) => envMap.get(v)?.present === true);
  const allInFile = !allPresent && model.env_vars.every((v) => {
    const s = envMap.get(v);
    return s?.present || s?.in_file;
  });
  const dotClass = allPresent ? "status-dot--ok" : allInFile ? "status-dot--warn" : "status-dot--missing";
  return (
    <div className="model-row">
      <div className="model-row__header">
        <span className="model-row__ref">{model.model_ref}</span>
        <span className="model-row__nick">({model.nickname})</span>
        <span className="model-row__provider">
          {model.provider}/{model.model_id}
        </span>
        <span className={`status-dot ${dotClass}`} />
      </div>
      <div className="model-row__detail">
        <span className="mono-sm">
          key: {model.api_key_env}
          {model.base_url_env && ` / url: ${model.base_url_env}`}
        </span>
        <span className="mono-sm">
          temp={model.temperature} max_tokens={model.max_tokens}
        </span>
      </div>
      <div className="model-row__actions">
        {isConfirmingRemove ? (
          <>
            <span className="model-row__confirm-text">Remove?</span>
            <button className="btn btn--sm btn--danger" onClick={onConfirmRemove}>
              Yes
            </button>
            <button className="btn btn--sm" onClick={onCancelRemove}>
              No
            </button>
          </>
        ) : (
          <>
            <button className="btn btn--sm" onClick={onEdit}>Edit</button>
            <button className="btn btn--sm" onClick={onRemove}>Remove</button>
          </>
        )}
      </div>
    </div>
  );
}

function ModelFormFields({
  form,
  setForm,
}: {
  form: ModelConfig;
  setForm: (f: ModelConfig) => void;
}) {
  const update = (patch: Partial<ModelConfig>) => setForm({ ...form, ...patch });
  return (
    <div className="model-form__fields">
      <div className="model-form__field">
        <label className="form-label">Provider</label>
        <select
          className="form-select"
          value={form.provider}
          onChange={(e) => update({ provider: e.target.value })}
        >
          {PROVIDERS.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </div>
      <div className="model-form__field">
        <label className="form-label">model_id</label>
        <input
          className="form-input"
          value={form.model_id}
          onChange={(e) => update({ model_id: e.target.value })}
          placeholder="e.g. gemini-2.5-flash"
        />
      </div>
      <div className="model-form__field">
        <label className="form-label">Nickname</label>
        <input
          className="form-input"
          value={form.nickname}
          onChange={(e) => update({ nickname: e.target.value })}
          placeholder="e.g. worker"
        />
      </div>
      <div className="model-form__field">
        <label className="form-label">api_key_env</label>
        <input
          className="form-input"
          value={form.api_key_env}
          onChange={(e) => update({ api_key_env: e.target.value })}
          placeholder="e.g. GOOGLE_API_KEY"
        />
      </div>
      {form.provider === "openai_compatible" && (
        <div className="model-form__field">
          <label className="form-label">base_url_env</label>
          <input
            className="form-input"
            value={form.base_url_env ?? ""}
            onChange={(e) => update({ base_url_env: e.target.value || undefined })}
            placeholder="e.g. PRIMARY_REVIEWER_BASE_URL"
          />
        </div>
      )}
      <div className="model-form__field model-form__field--half">
        <label className="form-label">Temperature</label>
        <input
          className="form-input form-input--narrow"
          type="number"
          step="0.1"
          min="0"
          max="2"
          value={form.temperature}
          onChange={(e) => update({ temperature: parseFloat(e.target.value) || 0 })}
        />
      </div>
      <div className="model-form__field model-form__field--half">
        <label className="form-label">Max tokens</label>
        <input
          className="form-input form-input--narrow"
          type="number"
          step="1024"
          min="256"
          value={form.max_tokens}
          onChange={(e) => update({ max_tokens: parseInt(e.target.value, 10) || 4096 })}
        />
      </div>
      <div className="model-form__field model-form__field--full">
        <label className="form-label">Description</label>
        <input
          className="form-input"
          value={form.description}
          onChange={(e) => update({ description: e.target.value })}
          placeholder="What is this model used for?"
        />
      </div>
    </div>
  );
}

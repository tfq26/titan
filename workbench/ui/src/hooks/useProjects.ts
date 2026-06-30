import { useState, useEffect, useCallback } from "react";
import type { ProjectEntry, ProjectConfig, ProjectAddInput } from "../types";
import { addProject as createProject, readRegistry, readProjectConfig } from "../bridge/files";

export function useProjects() {
  const [projects, setProjects] = useState<ProjectEntry[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [projectConfig, setProjectConfig] = useState<ProjectConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadProjects = useCallback(async () => {
    try {
      const reg = await readRegistry();
      setProjects(reg.projects);
      if (!selectedId && reg.projects.length > 0) {
        setSelectedId(reg.projects[0].id);
      }
    } catch (e) {
      setError(String(e));
    }
  }, [selectedId]);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    if (!selectedId) {
      setProjectConfig(null);
      return;
    }
    readProjectConfig(selectedId)
      .then(setProjectConfig)
      .catch((e) => setError(String(e)));
  }, [selectedId]);

  const refreshConfig = useCallback(async () => {
    if (!selectedId) return;
    try {
      const config = await readProjectConfig(selectedId);
      setProjectConfig(config);
    } catch (e) {
      setError(String(e));
    }
  }, [selectedId]);

  const selected = projects.find((p) => p.id === selectedId) ?? null;

  const addProject = useCallback(
    async (project: ProjectAddInput) => {
      const created = await createProject(project);
      await loadProjects();
      setSelectedId(created.id);
      return created;
    },
    [loadProjects]
  );

  return {
    projects,
    selected,
    selectedId,
    setSelectedId,
    projectConfig,
    error,
    refresh: loadProjects,
    refreshConfig,
    addProject,
  };
}

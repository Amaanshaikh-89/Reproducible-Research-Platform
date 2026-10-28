const API = "http://127.0.0.1:8000";

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item) => item.msg).filter(Boolean).join(" ")
      : body.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return body;
}

export const api = {
  experiments: () => request("/api/experiments"),
  experiment: (id) => request(`/api/experiments/${id}`),
  createExperiment: (data) => request("/api/experiments", {
    method: "POST", body: JSON.stringify(data),
  }),
  updateExperiment: (id, data) => request(`/api/experiments/${id}`, {
    method: "PUT", body: JSON.stringify(data),
  }),
  deleteExperiment: (id) =>
    request(`/api/experiments/${id}`, { method: "DELETE" }),
  runExperiment: (id) => request(`/api/experiments/${id}/run`, { method: "POST" }),
  runPolicies: (id) => request(`/api/policies/runs/${id}`),
  runDetails: (id) => request(`/api/runs/${id}`),
  compareRuns: (runAId, runBId) =>
    request(`/api/runs/compare?run_a_id=${runAId}&run_b_id=${runBId}`),
  auditEvents: async (limit = 100) => {
    const events = await request(`/api/audit-events?limit=${limit}`);
    if (!Array.isArray(events)) {
      throw new Error("The audit events response was not a list.");
    }
    return events;
  },
  runReport: async (runId) => {
    const response = await fetch(`${API}/api/runs/${runId}/report`);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Report download failed (${response.status})`);
    }
    return response.blob();
  },
  previewArtifact: (id) => request(`/api/artifacts/${id}/preview`),
  downloadArtifact: async (id) => {
    const response = await fetch(`${API}/api/artifacts/${id}/download`);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Download failed (${response.status})`);
    }
    return response.blob();
  },
  lineage: (id) => request(`/api/experiments/${id}/lineage`),
  policies: () => request("/api/policies"),
  artifacts: () => request("/api/artifacts"),
  deleteArtifact: (id) =>
    request(`/api/artifacts/${id}`, { method: "DELETE" }),
  health: () => request("/health"),
};

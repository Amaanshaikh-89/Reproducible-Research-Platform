
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  Archive,
  Beaker,
  CircleHelp,
  ClipboardList,
  Download,
  GitBranch,
  GitCompareArrows,
  LayoutDashboard,
  Play,
  Plus,
  RefreshCw,
  ShieldCheck,
  Terminal,
  Trash2,
  X,
  LoaderCircle,
  Database,
  CheckCircle2,
  Clock3,
  Pencil,
} from "lucide-react";

import { api } from "./api";
import StatCard from "./components/StatCard";
import LineageGraph from "./components/LineageGraph";
import PolicyResults from "./components/PolicyResults";
import RunComparison from "./components/RunComparison";
import AuditTrail from "./components/AuditTrail";
import EntityDetailModal from "./components/EntityDetailModal";
import ArtifactPreview from "./components/ArtifactPreview";

function timeLabel(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function valueText(value) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  return typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
}

function runDuration(startedAt, finishedAt) {
  if (!startedAt || !finishedAt) return "Not recorded";
  const milliseconds = new Date(finishedAt) - new Date(startedAt);
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return "Not recorded";
  return `${(milliseconds / 1000).toFixed(2)} seconds`;
}

function DetailFields({ items }) {
  return (
    <dl className="entity-detail-fields">
      {items.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>
            {value && typeof value === "object" ? (
              <pre>{JSON.stringify(value, null, 2)}</pre>
            ) : valueText(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function DetailSection({ title, children }) {
  return (
    <section className="entity-detail-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

const DEFAULT_SAMPLE_CODE = `import random
from statistics import mean

seed = int(parameters.get("seed", 42))
random.seed(seed)
values = [float(value) for value in input_data["values"]]

result = {
    "experiment": "sample descriptive statistics",
    "parameters": {"seed": seed},
    "metrics": {
        "row_count": len(values),
        "mean_value": round(mean(values), 4) if values else 0,
        "min_value": min(values) if values else None,
        "max_value": max(values) if values else None,
    },
    "reproducibility": {
        "random_seed": seed,
        "note": "Deterministic descriptive statistics for demo.",
    },
}`;

const DEFAULT_EXPERIMENT_FORM = {
  name: "Sample descriptive statistics",
  description: "Calculate descriptive statistics from the provided JSON values.",
  parameters: JSON.stringify({ seed: 42 }, null, 2),
  customCode: DEFAULT_SAMPLE_CODE,
  inputData: JSON.stringify(
    { values: [12.5, 18.0, 16.5, 21.0, 14.0, 19.5] },
    null,
    2
  ),
};

export default function App() {
  const [experiments, setExperiments] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [lineage, setLineage] = useState(null);
  const [lineageExperimentId, setLineageExperimentId] = useState(null);
  const [lineageLoading, setLineageLoading] = useState(false);
  const [lineageError, setLineageError] = useState("");
  const [policies, setPolicies] = useState([]);
  const [artifacts, setArtifacts] = useState([]);
  const [health, setHealth] = useState("checking");
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [deletingArtifactId, setDeletingArtifactId] = useState(null);
  const [deletingExperimentId, setDeletingExperimentId] = useState(null);
  const [notice, setNotice] = useState("");
  const [experimentDetail, setExperimentDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [runPolicies, setRunPolicies] = useState([]);
  const [policyRunId, setPolicyRunId] = useState(null);
  const [policiesLoading, setPoliciesLoading] = useState(false);
  const [policiesError, setPoliciesError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editingExperimentId, setEditingExperimentId] = useState(null);
  const [formError, setFormError] = useState("");
  const [reportDownloading, setReportDownloading] = useState(false);
  const [reportDownloadError, setReportDownloadError] = useState("");
  const [detailModal, setDetailModal] = useState(null);
  const [artifactPreview, setArtifactPreview] = useState(null);
  const selectedIdRef = useRef(null);
  const selectedRunIdRef = useRef(null);
  const activeSectionRef = useRef("overview");
  const refreshingRef = useRef(false);
  const screenRefreshRef = useRef(null);
  const runDetailsRef = useRef(null);
  const scrollToRunDetailsRef = useRef(false);
  const detailRequestRef = useRef(0);

  const [activeSection, setActiveSection] = useState("overview");
  activeSectionRef.current = activeSection;
  selectedRunIdRef.current = selectedRunId;

  const [form, setForm] = useState({ ...DEFAULT_EXPERIMENT_FORM });

  const selected =
    experiments.find((item) => item.id === selectedId) ||
    experiments[0] ||
    null;

  const sectionTitles = {
    overview: "Overview",
    experiments: "Experiments",
    lineage: "Artifact lineage",
    policies: "Policy gates",
    artifacts: "Artifacts",
    comparison: "Run comparison",
    audit: "Audit trail",
  };

  const selectExperiment = useCallback((id) => {
    selectedIdRef.current = id;
    setSelectedId(id);
  }, []);
  const registerScreenRefreshHandler = useCallback((handler) => {
    screenRefreshRef.current = handler;
  }, []);

  function openCreateExperiment() {
    setEditingExperimentId(null);
    setForm({ ...DEFAULT_EXPERIMENT_FORM });
    setFormError("");
    setShowForm(true);
  }

  function openEditExperiment(experiment) {
    setEditingExperimentId(experiment.id);
    setForm({
      name: experiment.name,
      description: experiment.description || "",
      parameters: JSON.stringify(experiment.parameters || {}, null, 2),
      customCode: experiment.custom_code || "",
      inputData: JSON.stringify(experiment.input_data || {}, null, 2),
    });
    setFormError("");
    setShowForm(true);
  }

  async function openEntityDetail(type, entity) {
    const requestId = ++detailRequestRef.current;
    setDetailModal({ type, entity, loading: true, error: "", data: null });
    setArtifactPreview(null);
    try {
      let data;
      if (type === "experiment") {
        data = await api.experiment(entity.experiment_id ?? entity.id);
      } else if (["run", "dataset", "code", "policy"].includes(type)) {
        data = await api.runDetails(entity.run_id ?? entity.id);
      } else if (type === "audit") {
        const ids = [entity.run_a_id, entity.run_b_id].filter((id) => id != null);
        const relatedRuns = await Promise.all(ids.map(async (id) => {
          try {
            return { id, details: await api.runDetails(id), error: "" };
          } catch (error) {
            return { id, details: null, error: error.message };
          }
        }));
        data = { event: entity, relatedRuns };
      } else {
        data = entity;
      }
      setDetailModal((current) =>
        current && requestId === detailRequestRef.current
          ? { ...current, loading: false, data }
          : current
      );
    } catch (error) {
      setDetailModal((current) =>
        current && requestId === detailRequestRef.current
          ? { ...current, loading: false, error: error.message }
          : current
      );
    }
  }

  function closeEntityDetail() {
    detailRequestRef.current += 1;
    setDetailModal(null);
  }

  function openArtifactDetail(artifact) {
    if (!artifact?.artifact_id && !artifact?.id) {
      openEntityDetail("artifact", artifact || {});
      return;
    }
    setDetailModal(null);
    setArtifactPreview({
      id: artifact.artifact_id ?? artifact.id,
      run_id: artifact.run_id,
      label: artifact.label ?? artifact.name,
    });
  }

  function openComparisonDetail(detail) {
    openEntityDetail("comparison", detail);
  }

  const refresh = useCallback(async () => {
    if (refreshingRef.current) return false;
    refreshingRef.current = true;
    setRefreshing(true);
    setNotice((current) =>
      current.startsWith("Could not refresh") ? "" : current
    );
    try {
      const [items, artifactItems, status, policyItems] = await Promise.all([
        api.experiments(),
        api.artifacts(),
        api.health(),
        api.policies(),
      ]);

      const currentId = selectedIdRef.current;
      const nextExperiment = items.find((item) => item.id === currentId) || items[0] || null;
      if (nextExperiment?.id !== currentId) {
        selectExperiment(nextExperiment?.id ?? null);
      }
      setExperiments(items);
      setArtifacts(artifactItems);
      setHealth(status.status);
      setPolicies(policyItems);

      if (!nextExperiment) {
        setExperimentDetail(null);
        setDetailError("");
        setSelectedRunId(null);
        setRunPolicies([]);
        setPolicyRunId(null);
        setLineage(null);
        setLineageExperimentId(null);
      } else {
        let detail;
        try {
          detail = await api.experiment(nextExperiment.id);
        } catch (error) {
          setDetailError(error.message);
          throw error;
        }
        if (selectedIdRef.current !== nextExperiment.id) return;

        setExperimentDetail(detail);
        setDetailError("");
        const oldRunId = selectedRunIdRef.current;
        const nextRunId = detail.runs?.some((run) => run.id === oldRunId)
          ? oldRunId
          : detail.runs?.[0]?.id ?? null;
        if (nextRunId !== oldRunId) setSelectedRunId(nextRunId);

        if (
          nextRunId &&
          ["experiments", "policies"].includes(activeSectionRef.current)
        ) {
          setPoliciesLoading(true);
          setPoliciesError("");
          try {
            const checks = await api.runPolicies(nextRunId);
            if (selectedIdRef.current === nextExperiment.id) {
              setRunPolicies(checks);
              setPolicyRunId(nextRunId);
            }
          } catch (error) {
            setPoliciesError(error.message);
            throw error;
          } finally {
            setPoliciesLoading(false);
          }
        } else if (!nextRunId) {
          setRunPolicies([]);
          setPolicyRunId(null);
        }

        if (activeSectionRef.current === "lineage") {
          setLineageLoading(true);
          setLineageError("");
          try {
            const graph = await api.lineage(nextExperiment.id);
            if (selectedIdRef.current === nextExperiment.id) {
              setLineage(graph);
              setLineageExperimentId(nextExperiment.id);
            }
          } catch (error) {
            setLineage(null);
            setLineageExperimentId(null);
            setLineageError(error.message);
            throw error;
          } finally {
            setLineageLoading(false);
          }
        }
      }

      const refreshScreen = screenRefreshRef.current;
      if (refreshScreen) await refreshScreen();
      return true;
    } catch (error) {
      setNotice(
        `Could not refresh ${sectionTitles[activeSectionRef.current]?.toLowerCase() || "application"}: ${error.message}`
      );
      return false;
    } finally {
      refreshingRef.current = false;
      setRefreshing(false);
    }
  }, [selectExperiment]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!selected?.id) {
      setLineage(null);
      setLineageExperimentId(null);
      setLineageLoading(false);
      setLineageError("");
      return;
    }

    let cancelled = false;
    setLineage(null);
    setLineageExperimentId(null);
    setLineageLoading(true);
    setLineageError("");
    setExperimentDetail(null);
    setDetailLoading(true);
    setDetailError("");
    setSelectedRunId(null);
    setRunPolicies([]);
    setPoliciesError("");

    api
      .experiment(selected.id)
      .then((detail) => {
        if (cancelled) return;
        setExperimentDetail(detail);
        setSelectedRunId(detail.runs?.[0]?.id ?? null);
      })
      .catch((error) => {
        if (cancelled) return;
        setDetailError(error.message);
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });

    api
      .lineage(selected.id)
      .then((graph) => {
        if (!cancelled) {
          setLineage(graph);
          setLineageExperimentId(selected.id);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setLineage(null);
          setLineageError(error.message);
        }
      })
      .finally(() => {
        if (!cancelled) setLineageLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selected?.id]);

  const currentExperimentDetail =
    experimentDetail?.id === selected?.id ? experimentDetail : null;
  const selectedRun =
    currentExperimentDetail?.runs?.find((run) => run.id === selectedRunId) ??
    null;

  useEffect(() => {
    if (!scrollToRunDetailsRef.current || !selectedRun) return;
    scrollToRunDetailsRef.current = false;
    requestAnimationFrame(() => {
      runDetailsRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
  }, [selectedRun]);

  function viewRunDetails(runId) {
    setReportDownloadError("");
    if (runId === selectedRunId && selectedRun) {
      runDetailsRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
      return;
    }
    scrollToRunDetailsRef.current = true;
    setSelectedRunId(runId);
  }

  const selectedRunArtifacts = artifacts.filter(
    (artifact) => artifact.run_id === selectedRunId
  );
  const selectedRunPolicies =
    policyRunId === selectedRunId ? runPolicies : [];
  const passCount =
    selectedRunPolicies.filter((check) => check.passed).length;

  const totalChecks = selectedRunPolicies.length;

  const runCount = experiments.filter((item) => item.last_run_id).length;
  const metrics = selectedRun?.metrics || {};

  useEffect(() => {
    if (!selectedRunId) {
      setRunPolicies([]);
      setPolicyRunId(null);
      setPoliciesLoading(false);
      setPoliciesError("");
      return;
    }

    let cancelled = false;
    setRunPolicies([]);
    setPolicyRunId(null);
    setPoliciesLoading(true);
    setPoliciesError("");

    api
      .runPolicies(selectedRunId)
      .then((checks) => {
        if (!cancelled) {
          setRunPolicies(checks);
          setPolicyRunId(selectedRunId);
        }
      })
      .catch((error) => {
        if (!cancelled) setPoliciesError(error.message);
      })
      .finally(() => {
        if (!cancelled) setPoliciesLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedRunId]);

  async function createExperiment(event) {
    event.preventDefault();
    setFormError("");
    let inputData;
    let parameters;
    try {
      inputData = JSON.parse(form.inputData);
    } catch {
      setFormError("Input data must be valid JSON. Check the quotes, commas, and brackets.");
      return;
    }
    try {
      parameters = JSON.parse(form.parameters);
    } catch {
      setFormError("Parameters must be valid JSON. Check the quotes, commas, and brackets.");
      return;
    }
    if (!inputData || Array.isArray(inputData) || typeof inputData !== "object") {
      setFormError("Input data must be a JSON object, such as {\"values\": [1, 2, 3]}.");
      return;
    }
    if (!parameters || Array.isArray(parameters) || typeof parameters !== "object") {
      setFormError("Parameters must be a JSON object, such as {\"seed\": 42}.");
      return;
    }
    setBusy(true);

    try {
      const payload = {
        name: form.name,
        description: form.description,
        parameters,
        custom_code: form.customCode,
        input_data: inputData,
      };
      const saved = editingExperimentId === null
        ? await api.createExperiment(payload)
        : await api.updateExperiment(editingExperimentId, payload);

      selectExperiment(saved.id);
      setActiveSection("experiments");
      setShowForm(false);
      setNotice(editingExperimentId === null
        ? `Experiment #${saved.id} created.`
        : `Experiment #${saved.id} updated.`);
      setEditingExperimentId(null);
      await refresh();
    } catch (error) {
      setFormError(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function runExperiment(id) {
    selectExperiment(id);
    setBusy(true);
    const selectedExperiment = experiments.find((item) => item.id === id);
    setNotice(!selectedExperiment?.custom_code?.trim()
      ? "This experiment has no saved Python code. Edit it and save code before running."
      : "Running your custom Python experiment in Docker. The first run may download the Python image…");
    setSelectedRunId(null);

    try {
      const result = await api.runExperiment(id);

      setNotice(
        result.status === "succeeded"
          ? "Experiment completed. Artifact and policy results recorded."
          : `Run failed: ${result.message}`
      );

      await refresh();

      const detail = await api.experiment(id);
      if (selectedIdRef.current === id) {
        setExperimentDetail(detail);
        setSelectedRunId(result.run_id);
        setLineageLoading(true);
        setLineageError("");
        try {
          const graph = await api.lineage(id);
          if (selectedIdRef.current === id) {
            setLineage(graph);
            setLineageExperimentId(id);
          }
        } catch (error) {
          if (selectedIdRef.current === id) {
            setLineage(null);
            setLineageExperimentId(null);
            setLineageError(error.message);
          }
        } finally {
          if (selectedIdRef.current === id) setLineageLoading(false);
        }
      }
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function deleteExperiment(item) {
    const confirmed = window.confirm(
      `Delete experiment "${item.name}" (ID ${item.id})?\n\nThis permanently deletes the experiment, its runs and recorded provenance, registered artifact records and files that are not shared by another artifact, and saved policy checks. Provenance reports for these runs can no longer be generated. Audit events are preserved, but references to deleted run IDs will be cleared.`
    );
    if (!confirmed) return;

    setDeletingExperimentId(item.id);
    setNotice("");
    try {
      const result = await api.deleteExperiment(item.id);
      setExperiments((current) =>
        current.filter((entry) => entry.id !== item.id)
      );
      if (selectedIdRef.current === item.id) {
        selectedIdRef.current = null;
        setSelectedId(null);
        setSelectedRunId(null);
        setExperimentDetail(null);
      }
      setNotice(
        result.cleanup_warning
          ? `Experiment "${item.name}" was deleted, but some artifact files could not be removed safely.`
          : `Experiment "${item.name}" and its associated records were deleted. Audit events were preserved.`
      );
      await refresh();
    } catch (error) {
      setNotice(`Could not delete experiment "${item.name}": ${error.message}`);
    } finally {
      setDeletingExperimentId(null);
    }
  }

  async function deleteArtifact(artifact) {
    const confirmed = window.confirm(
      `Delete artifact "${artifact.name}" (ID ${artifact.id}, run ${artifact.run_id})?\n\nThis removes only the artifact registry entry and its stored file if no other artifact record references that file. The run, experiment, provenance and audit history will remain.`
    );
    if (!confirmed) return;

    setDeletingArtifactId(artifact.id);
    setNotice("");
    try {
      const result = await api.deleteArtifact(artifact.id);
      setArtifacts((current) =>
        current.filter((entry) => entry.id !== artifact.id)
      );
      setNotice(
        result.cleanup_warning
          ? `Artifact "${artifact.name}" was removed from the registry, but its file could not be removed safely.`
          : `Artifact "${artifact.name}" deleted. Its run and provenance were preserved.`
      );
      await refresh();
    } catch (error) {
      setNotice(`Could not delete artifact "${artifact.name}": ${error.message}`);
    } finally {
      setDeletingArtifactId(null);
    }
  }

  async function downloadRunReport(runId) {
    setReportDownloading(true);
    setReportDownloadError("");
    try {
      const blob = await api.runReport(runId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `run-${runId}-provenance.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      setReportDownloadError(error.message);
    } finally {
      setReportDownloading(false);
    }
  }

  function navigate(section) {
    setActiveSection(section);
    setNotice("");
  }

  function navItem(section, Icon, label) {
    return (
      <button
        key={section}
        type="button"
        className={`nav-item ${
          activeSection === section ? "active" : ""
        }`}
        onClick={() => navigate(section)}
      >
        <Icon size={17} />
        <span>{label}</span>
      </button>
    );
  }

  function relatedRunButton(runId) {
    return (
      <button
        type="button"
        className="text-button entity-related-button"
        key={runId}
        onClick={() => openEntityDetail("run", { id: runId })}
      >
        Run #{runId}
      </button>
    );
  }

  function relatedArtifactButton(artifact) {
    return (
      <button
        type="button"
        className="text-button entity-related-button"
        key={artifact.id}
        onClick={() => openArtifactDetail(artifact)}
      >
        {artifact.name} · Artifact #{artifact.id}
      </button>
    );
  }

  function detailTitle() {
    if (!detailModal) return "Details";
    const { type, entity, data } = detailModal;
    if (type === "experiment") return data?.name || entity.label || `Experiment #${entity.id}`;
    if (type === "run") return data?.run ? `Run #${data.run.id}` : `Run #${entity.run_id ?? entity.id}`;
    if (type === "dataset") return entity.label || "Dataset input";
    if (type === "code") return entity.label || "Experiment code";
    if (type === "policy") return entity.check?.policy_name?.replaceAll("_", " ") || "Policy check";
    if (type === "audit") return `Audit event #${entity.id}`;
    if (type === "comparison") return entity.label || entity.name || "Comparison detail";
    return "Entity details";
  }

  function renderEntityContent() {
    if (!detailModal) return null;
    const { type, entity, data } = detailModal;
    if (detailModal.loading) return <div className="empty" role="status">Loading {type} details…</div>;
    if (detailModal.error) return <div className="empty error-text" role="alert">Could not load {type} details: {detailModal.error}</div>;
    if (type === "experiment") {
      if (!data) return <div className="empty">Experiment details are unavailable.</div>;
      const runIds = new Set((data.runs || []).map((run) => run.id));
      const relatedArtifacts = artifacts.filter((artifact) => runIds.has(artifact.run_id));
      return <>
        <DetailFields items={[
          ["Experiment ID", data.id], ["Name", data.name], ["Description", data.description || "Not recorded"],
          ["Created", data.created_at ? timeLabel(data.created_at) : "Not recorded"],
          ["Status", data.status], ["Parameters", data.parameters], ["Input data", data.input_data],
          ["Custom code stored", data.custom_code ? "Yes" : "No; save Python code before running"],
        ]} />
        <DetailSection title={`Runs (${(data.runs || []).length})`}>
          {data.runs?.length ? <div className="entity-related-list">{data.runs.map((run) => relatedRunButton(run.id))}</div> : <p className="muted small">No runs are recorded for this experiment.</p>}
        </DetailSection>
        <DetailSection title={`Artifacts (${relatedArtifacts.length})`}>
          {relatedArtifacts.length ? <div className="entity-related-list">{relatedArtifacts.map(relatedArtifactButton)}</div> : <p className="muted small">No registered artifacts are associated with these runs.</p>}
        </DetailSection>
      </>;
    }
    if (["run", "dataset", "code", "policy"].includes(type)) {
      if (!data?.run) return <div className="empty">Run details are unavailable.</div>;
      const run = data.run;
      const experiment = data.experiment;
      const artifactsForRun = data.artifacts || [];
      const checks = data.policy_checks || [];
      if (type === "dataset") {
        const custom = Boolean(experiment.custom_code);
        return <>
          <DetailFields items={[
            ["Dataset", entity.label], ["Experiment", `${experiment.name} (#${experiment.id})`],
            ["Run", `#${run.id}`], ["SHA-256", entity.sha256 || run.dataset_sha256],
            ["Source", entity.source], ["Source type", entity.source_kind],
            ["Storage", custom ? "Input JSON is stored with the experiment configuration." : "No saved input configuration is available for this legacy run."],
          ]} />
          {custom ? <DetailSection title="Stored JSON input"><pre className="entity-detail-code">{JSON.stringify(experiment.input_data, null, 2)}</pre></DetailSection> : <p className="muted small">This historical run has no saved JSON input associated with its experiment definition.</p>}
          <DetailSection title="Related artifacts">{artifactsForRun.length ? <div className="entity-related-list">{artifactsForRun.map(relatedArtifactButton)}</div> : <p className="muted small">No artifacts are registered for this run.</p>}</DetailSection>
        </>;
      }
      if (type === "code") {
        return <>
          <DetailFields items={[
            ["Code file", entity.label], ["Experiment", `${experiment.name} (#${experiment.id})`],
            ["Run", `#${run.id}`], ["SHA-256", entity.sha256 || run.code_sha256],
            ["Source type", entity.source_kind], ["Availability", entity.source_note],
          ]} />
          {experiment.custom_code ? <DetailSection title="Stored submitted source"><pre className="entity-detail-code">{experiment.custom_code}</pre></DetailSection> : <p className="muted small">This experiment has no saved Python source. The recorded hash cannot recover the source; edit and save code before running it again.</p>}
        </>;
      }
      if (type === "policy") {
        const check = checks.find((item) => item.policy_name === entity.check?.policy_name) || entity.check;
        return <>
          <DetailFields items={[
            ["Policy", check?.policy_name?.replaceAll("_", " ")], ["Status", check?.passed ? "Passed" : "Failed"],
            ["Recorded reason", check?.message], ["Checked at", check?.checked_at ? timeLabel(check.checked_at) : "Not recorded"],
            ["Associated run", `#${run.id}`], ["Experiment", `${experiment.name} (#${experiment.id})`],
          ]} />
          {relatedRunButton(run.id)}
        </>;
      }
      return <>
        <DetailFields items={[
          ["Run ID", run.id], ["Status", run.status], ["Started", run.started_at ? timeLabel(run.started_at) : "Not recorded"],
          ["Completed", run.finished_at ? timeLabel(run.finished_at) : "Not recorded"],
          ["Duration", runDuration(run.started_at, run.finished_at)],
          ["Experiment", `${experiment.name} (#${experiment.id})`], ["Parameters", run.parameters], ["Metrics", run.metrics],
          ["Docker image", run.docker_image], ["Docker image digest", run.docker_image_digest],
          ["Code SHA-256", run.code_sha256], ["Dataset SHA-256", run.dataset_sha256],
          ["Configuration SHA-256", run.configuration_sha256],
          ...(run.status === "failed" ? [["Recorded error", run.message]] : []),
        ]} />
        <DetailSection title={`Artifacts (${artifactsForRun.length})`}>
          {artifactsForRun.length ? <div className="entity-related-list">{artifactsForRun.map(relatedArtifactButton)}</div> : <p className="muted small">No artifacts are registered for this run.</p>}
        </DetailSection>
        <DetailSection title={`Policy checks (${checks.length})`}>
          {checks.length ? <div className="entity-related-list">{checks.map((check) => <button key={check.id} type="button" className="text-button entity-related-button" onClick={() => openEntityDetail("policy", { run_id: run.id, check })}>{check.passed ? "PASS" : "FAIL"} · {check.policy_name.replaceAll("_", " ")}</button>)}</div> : <p className="muted small">No policy checks are recorded for this run.</p>}
        </DetailSection>
      </>;
    }
    if (type === "audit") {
      const event = data?.event || entity;
      return <>
        <DetailFields items={[
          ["Event ID", event.id], ["Event", event.event_type], ["Occurred", event.occurred_at ? timeLabel(event.occurred_at) : "Not recorded"],
          ["Result", event.result], ["Run A", event.run_a_id == null ? "Run removed" : `#${event.run_a_id}`],
          ["Run B", event.run_b_id == null ? "Run removed" : `#${event.run_b_id}`],
        ]} />
        <DetailSection title="Associated runs">
          {data?.relatedRuns?.length ? <div className="entity-related-list">{data.relatedRuns.map((related) => related.details ? relatedRunButton(related.id) : <span className="muted small" key={related.id}>Run #{related.id} is unavailable: {related.error}</span>)}</div> : <p className="muted small">This event has no associated runs.</p>}
        </DetailSection>
      </>;
    }
    if (type === "comparison") {
      const comparison = entity.comparison;
      const metric = entity.metric;
      if (metric) return <DetailFields items={[
        ["Metric", metric.name], ["Run A", comparison?.run_a?.id], ["Run A value", metric.run_a],
        ["Run B", comparison?.run_b?.id], ["Run B value", metric.run_b],
        ["Difference (B − A)", metric.status === "COMPARABLE" ? metric.difference : "Not comparable"], ["Comparison status", metric.status],
      ]} />;
      const field = entity.field;
      return <DetailFields items={[
        ["Provenance field", field?.label || field?.field], ["Run A", comparison?.run_a?.id], ["Run A recorded value", field?.run_a],
        ["Run B", comparison?.run_b?.id], ["Run B recorded value", field?.run_b], ["Recorded comparison", field?.status],
      ]} />;
    }
    return <div className="empty">Details are unavailable for this entity.</div>;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Beaker size={21} />
          </div>
          <div>
            <strong>ResearchLab</strong>
            <span>REPRODUCIBILITY PLATFORM</span>
          </div>
        </div>

        <div className="workspace-label">WORKSPACE</div>

        <nav>
          {navItem("overview", LayoutDashboard, "Overview")}
          {navItem("experiments", Activity, "Experiments")}
          {navItem("lineage", GitBranch, "Artifact lineage")}
          {navItem("policies", ShieldCheck, "Policy gates")}
          {navItem("artifacts", Archive, "Artifacts")}
          {navItem("comparison", GitCompareArrows, "Run comparison")}
          {navItem("audit", ClipboardList, "Audit trail")}
        </nav>

        <div className="sidebar-bottom">
          <div className="backend-status">
            <span
              className={`status-dot ${
                health === "healthy" ? "online" : "offline"
              }`}
            />
            <div>
              <strong>
                {health === "healthy"
                  ? "Backend connected"
                  : health === "checking"
                  ? "Connecting…"
                  : "Backend offline"}
              </strong>
              <span>Local development</span>
            </div>
          </div>

          <div className="sidebar-note">
            <CircleHelp size={16} />
            <span>Research prototype · v1.0</span>
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <span className="breadcrumb">Workspace /</span>{" "}
            {sectionTitles[activeSection]}
          </div>

          <div className="top-actions">
            <span className="local-badge">
              <span className="status-dot online" />
              Local environment
            </span>

            <button
              type="button"
              className={`icon-button ${refreshing ? "refreshing" : ""}`}
              title="Refresh"
              onClick={refresh}
              disabled={
                refreshing ||
                deletingArtifactId !== null ||
                deletingExperimentId !== null
              }
              aria-label="Refresh current screen data"
              aria-busy={refreshing}
            >
              <RefreshCw size={17} className={refreshing ? "spin" : ""} />
            </button>
          </div>
        </header>

        <div className="content">
          {notice && (
            <div
              className={`notice ${
                notice.startsWith("Run failed") ||
                notice.startsWith("Backend unavailable") ||
                notice.startsWith("Could not") ||
                notice.includes("could not be removed safely")
                  ? "notice-warning"
                  : ""
              }`}
            >
              <span>{notice}</span>
              <button
                type="button"
                className="notice-close"
                onClick={() => setNotice("")}
              >
                <X size={15} />
              </button>
            </div>
          )}

          {/* OVERVIEW */}
          {activeSection === "overview" && (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">RESEARCH OPERATIONS</div>
                  <h1>Reproducibility overview</h1>
                  <p>
                    Track experiments, trace artifacts, and enforce research
                    quality policies.
                  </p>
                </div>

                <button
                  type="button"
                  className="button button-primary"
                  onClick={openCreateExperiment}
                >
                  <Plus size={17} /> New experiment
                </button>
              </div>

              <div className="stat-grid">
                <StatCard
                  label="Experiments"
                  value={experiments.length}
                  note="Registered in this workspace"
                  icon={Beaker}
                  onClick={() => navigate("experiments")}
                />
                <StatCard
                  label="Runs recorded"
                  value={runCount}
                  note="Experiments with a run"
                  icon={Activity}
                  onClick={() => navigate("experiments")}
                />
                <StatCard
                  label="Artifacts"
                  value={artifacts.length}
                  note="Stored output files"
                  icon={Archive}
                  onClick={() => navigate("artifacts")}
                />
                <StatCard
                  label="Policy rules"
                  value={policies.length}
                  note="Configured validation checks"
                  icon={ShieldCheck}
                  onClick={() => navigate("policies")}
                />
              </div>

              <section className="panel">
                <div className="panel-header">
                  <div>
                    <h2>Recent experiments</h2>
                    <p>
                      Your registered experiments and their current status.
                    </p>
                  </div>
                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => navigate("experiments")}
                  >
                    View all
                  </button>
                </div>

                {experiments.length === 0 ? (
                  <div className="empty-state">
                    <div className="empty-icon">
                      <Beaker size={25} />
                    </div>
                    <h3>No experiments yet</h3>
                    <p>Create your first experiment to get started.</p>
                    <button
                      type="button"
                      className="button button-primary"
                      onClick={openCreateExperiment}
                    >
                      <Plus size={16} /> Create first experiment
                    </button>
                  </div>
                ) : (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>EXPERIMENT</th>
                          <th>STATUS</th>
                          <th>CREATED</th>
                          <th>ACTION</th>
                        </tr>
                      </thead>
                      <tbody>
                        {experiments.slice(0, 5).map((item) => (
                          <tr key={item.id}>
                            <td>
                              <button
                                type="button"
                                className="text-button experiment-name"
                                onClick={() => openEntityDetail("experiment", { id: item.id, label: item.name })}
                              >
                                {item.name}
                              </button>
                              <div className="muted small">
                                {item.description || "No description"}
                              </div>
                            </td>
                            <td>
                              <span
                                className={`pill ${
                                  item.status === "succeeded"
                                    ? "pill-success"
                                    : item.status === "failed"
                                    ? "pill-danger"
                                    : "pill-neutral"
                                }`}
                              >
                                {item.status}
                              </span>
                            </td>
                            <td className="muted small">
                              {timeLabel(item.created_at)}
                            </td>
                            <td>
                              <button
                                type="button"
                                className="button button-run"
                                disabled={busy}
                                onClick={() => {
                                  navigate("experiments");
                                  runExperiment(item.id);
                                }}
                              >
                                <Play size={14} fill="currentColor" /> Run
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              {selectedRun && (
                <section className="panel run-output">
                  <div className="panel-header">
                    <div>
                      <h2>
                        <Terminal size={17} /> Selected execution output
                      </h2>
                      <p>Results from the selected historical run.</p>
                    </div>
                    <span className="muted small">
                      Run #{selectedRun.id}
                    </span>
                  </div>

                  <div
                    className={`run-message ${
                      selectedRun.status === "succeeded"
                        ? "success-message"
                        : "error-message"
                    }`}
                  >
                    {selectedRun.message}
                  </div>

                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => navigate("experiments")}
                  >
                    View full execution results
                  </button>
                </section>
              )}
            </>
          )}

          {/* EXPERIMENTS */}
          {activeSection === "experiments" && (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">RESEARCH WORKSPACE</div>
                  <h1>Experiments</h1>
                  <p>Create experiments with custom Python code and JSON inputs.</p>
                </div>

                <button
                  type="button"
                  className="button button-primary"
                  onClick={openCreateExperiment}
                >
                  <Plus size={17} /> Create experiment
                </button>
              </div>

              <section className="panel">
                <div className="panel-header">
                  <div>
                    <h2>Experiment registry</h2>
                    <p>Select an experiment or start a new run.</p>
                  </div>
                  <span className="count-badge">
                    {experiments.length} experiments
                  </span>
                </div>

                {experiments.length === 0 ? (
                  <div className="empty-state">
                    <div className="empty-icon">
                      <Beaker size={25} />
                    </div>
                    <h3>No experiments yet</h3>
                    <p>Create an experiment to begin.</p>
                    <button
                      type="button"
                      className="button button-primary"
                      onClick={openCreateExperiment}
                    >
                      <Plus size={16} /> Create experiment
                    </button>
                  </div>
                ) : (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>EXPERIMENT</th>
                          <th>STATUS</th>
                          <th>CREATED</th>
                          <th>ACTION</th>
                        </tr>
                      </thead>
                      <tbody>
                        {experiments.map((item) => (
                          <tr
                            key={item.id}
                            className={
                              selected?.id === item.id ? "selected-row" : ""
                            }
                          >
                            <td>
                              <button
                                type="button"
                                className="text-button experiment-name"
                                onClick={() => {
                                  selectExperiment(item.id);
                                  openEntityDetail("experiment", { id: item.id, label: item.name });
                                }}
                              >
                                {item.name}
                              </button>
                              <div className="muted small">
                                {item.description || "No description"}
                              </div>
                              <button type="button" className="text-button muted tiny" onClick={() => openEntityDetail("experiment", { id: item.id, label: item.name })}>
                                ID: EXP-{String(item.id).padStart(4, "0")}
                              </button>
                            </td>
                            <td>
                              <span
                                className={`pill ${
                                  item.status === "succeeded"
                                    ? "pill-success"
                                    : item.status === "failed"
                                    ? "pill-danger"
                                    : "pill-neutral"
                                }`}
                              >
                                {item.status}
                              </span>
                            </td>
                            <td className="muted small">
                              {timeLabel(item.created_at)}
                            </td>
                            <td>
                              <button
                                type="button"
                                className="button button-secondary"
                                disabled={busy || refreshing || deletingExperimentId !== null}
                                onClick={() => openEditExperiment(item)}
                                aria-label={`Edit experiment ${item.name}`}
                              >
                                <Pencil size={14} /> Edit
                              </button>
                              <button
                                type="button"
                                className="button button-run"
                                disabled={
                                  busy ||
                                  refreshing ||
                                  deletingArtifactId !== null ||
                                  deletingExperimentId !== null
                                }
                                onClick={() => runExperiment(item.id)}
                              >
                                <Play size={14} fill="currentColor" /> Run
                              </button>
                              <button
                                type="button"
                                className="button button-secondary danger"
                                disabled={
                                  busy ||
                                  refreshing ||
                                  deletingArtifactId !== null ||
                                  deletingExperimentId !== null
                                }
                                onClick={() => deleteExperiment(item)}
                                aria-label={`Delete experiment ${item.name}`}
                                title={`Delete ${item.name}`}
                              >
                                <Trash2 size={14} />
                                {deletingExperimentId === item.id
                                  ? "Deleting…"
                                  : "Delete"}
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              <section className="panel">
                <div className="panel-header">
                  <div>
                    <h2>Run history</h2>
                    <p>
                      {selected
                        ? `Execution history for ${selected.name}. Select a run to inspect its saved results.`
                        : "Select an experiment to view its run history."}
                    </p>
                  </div>
                  {currentExperimentDetail?.runs?.length > 0 && (
                    <span className="count-badge">
                      {currentExperimentDetail.runs.length} runs
                    </span>
                  )}
                </div>

                {detailLoading || (selected && !currentExperimentDetail && !detailError) ? (
                  <div className="empty">Loading experiment run history…</div>
                ) : detailError ? (
                  <div className="empty error-text">
                    Could not load run history: {detailError}
                  </div>
                ) : !selected ? (
                  <div className="empty">Create an experiment to view run history.</div>
                ) : !currentExperimentDetail?.runs?.length ? (
                  <div className="empty">
                    No runs recorded for this experiment yet. Run it to create history.
                  </div>
                ) : (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>RUN</th>
                          <th>STATUS</th>
                          <th>STARTED</th>
                          <th>COMPLETED</th>
                          <th>MESSAGE</th>
                          <th>ACTION</th>
                        </tr>
                      </thead>
                      <tbody>
                        {currentExperimentDetail.runs.map((run) => (
                          <tr
                            key={run.id}
                            className={selectedRunId === run.id ? "selected-row" : ""}
                          >
                            <td><button type="button" className="text-button" onClick={() => openEntityDetail("run", { id: run.id })}>#{run.id}</button></td>
                            <td>
                              <span
                                className={`pill ${
                                  run.status === "succeeded"
                                    ? "pill-success"
                                    : run.status === "failed"
                                    ? "pill-danger"
                                    : "pill-neutral"
                                }`}
                              >
                                {run.status}
                              </span>
                            </td>
                            <td className="muted small">{timeLabel(run.started_at)}</td>
                            <td className="muted small">{timeLabel(run.finished_at)}</td>
                            <td className="run-history-message">{run.message || "—"}</td>
                            <td>
                              <button
                                type="button"
                                className="button button-secondary"
                                aria-pressed={selectedRunId === run.id}
                                onClick={() => viewRunDetails(run.id)}
                              >
                                View details
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              {selectedRun && (
                <section className="panel run-output" ref={runDetailsRef}>
                  <div className="panel-header">
                    <div>
                      <h2>
                        <Terminal size={17} /> Run #{selectedRun.id} details
                      </h2>
                      <p>
                        Started {timeLabel(selectedRun.started_at)} · Completed{" "}
                        {timeLabel(selectedRun.finished_at)}
                      </p>
                    </div>
                    <span
                      className={`pill ${
                        selectedRun.status === "succeeded"
                          ? "pill-success"
                          : selectedRun.status === "failed"
                          ? "pill-danger"
                          : "pill-neutral"
                      }`}
                    >
                      {selectedRun.status}
                    </span>
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => downloadRunReport(selectedRun.id)}
                      disabled={reportDownloading}
                    >
                      <Download size={15} />
                      {reportDownloading ? "Preparing report…" : "Download provenance report"}
                    </button>
                  </div>

                  {reportDownloadError && (
                    <div className="comparison-error" role="alert">
                      Could not download provenance report: {reportDownloadError}
                    </div>
                  )}

                  {selectedRun.message && (
                    <div
                      className={`run-message ${
                        selectedRun.status === "succeeded"
                          ? "success-message"
                          : "error-message"
                      }`}
                    >
                      {selectedRun.message}
                    </div>
                  )}

                  {Object.keys(metrics).length > 0 ? (
                    <div className="metrics-grid">
                      {Object.entries(metrics).map(([key, value]) => (
                        <div className="metric" key={key}>
                          <span>{key.replaceAll("_", " ")}</span>
                          <strong>{String(value)}</strong>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="empty">No metrics recorded for this run.</div>
                  )}

                  <div className="run-metadata">
                    <div>
                      <strong>Code SHA-256</strong>
                      <code>{selectedRun.code_sha256 || "Not recorded"}</code>
                    </div>
                    <div>
                      <strong>Dataset SHA-256</strong>
                      <code>{selectedRun.dataset_sha256 || "Not recorded"}</code>
                    </div>
                    <div>
                      <strong>Configuration SHA-256</strong>
                      <code>{selectedRun.configuration_sha256 || "Not recorded"}</code>
                    </div>
                    <div>
                      <strong>Docker image</strong>
                      <code>{selectedRun.docker_image || "Not recorded"}</code>
                    </div>
                    <div>
                      <strong>Docker image digest</strong>
                      <code>{selectedRun.docker_image_digest || "Not recorded"}</code>
                    </div>
                    <div>
                      <strong>Parameters</strong>
                      <code>{JSON.stringify(selectedRun.parameters || {})}</code>
                    </div>
                  </div>

                  <div className="panel-header run-subheading">
                    <div>
                      <h2>Artifacts</h2>
                      <p>Files recorded for this run.</p>
                    </div>
                  </div>
                  {selectedRunArtifacts.length ? (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>ARTIFACT</th>
                            <th>PATH</th>
                            <th>SHA-256</th>
                            <th>SIZE</th>
                            <th>CREATED</th>
                            <th>ACTION</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedRunArtifacts.map((artifact) => (
                            <tr key={artifact.id}>
                              <td><button type="button" className="text-button" onClick={() => openArtifactDetail(artifact)}>{artifact.name}</button></td>
                              <td className="muted small">{artifact.relative_path || "—"}</td>
                              <td><code className="hash">{artifact.sha256 || "—"}</code></td>
                              <td>{artifact.size_bytes} B</td>
                              <td className="muted small">{timeLabel(artifact.created_at)}</td>
                              <td>
                                <a
                                  className="button button-secondary"
                                  href={`http://127.0.0.1:8000/api/artifacts/${artifact.id}/download`}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  Download
                                </a>
                                <button
                                  type="button"
                                  className="button button-secondary danger"
                                  disabled={
                                    refreshing ||
                                    deletingArtifactId !== null ||
                                    deletingExperimentId !== null
                                  }
                                  onClick={() => deleteArtifact(artifact)}
                                  aria-label={`Delete artifact ${artifact.name}`}
                                  title={`Delete ${artifact.name}`}
                                >
                                  <Trash2 size={14} />
                                  {deletingArtifactId === artifact.id
                                    ? "Deleting…"
                                    : "Delete"}
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="empty">No artifact is recorded for this run.</div>
                  )}

                  <div className="panel-header run-subheading">
                    <div>
                      <h2><ShieldCheck size={17} /> Saved policy checks</h2>
                      <p>Policy results loaded for the selected run.</p>
                    </div>
                  </div>
                  {policiesLoading || policyRunId !== selectedRunId ? (
                    <div className="empty">Loading policy checks…</div>
                  ) : policiesError ? (
                    <div className="empty error-text">
                      Could not load policy checks: {policiesError}
                    </div>
                  ) : selectedRunPolicies.length ? (
                    <>
                      <PolicyResults checks={selectedRunPolicies} onSelectCheck={(check) => openEntityDetail("policy", { run_id: selectedRun.id, check })} />
                      <div className="policy-summary">
                        <span>Run #{selectedRun.id}</span>
                        <strong className={passCount === totalChecks ? "success" : "danger"}>
                          {passCount}/{totalChecks} passed
                        </strong>
                      </div>
                    </>
                  ) : (
                    <div className="empty">No policy checks are saved for this run.</div>
                  )}

                  <div className="panel-actions">
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => navigate("lineage")}
                    >
                      <GitBranch size={16} /> View lineage
                    </button>
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => navigate("artifacts")}
                    >
                      <Archive size={16} /> View artifacts
                    </button>
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => navigate("policies")}
                    >
                      <ShieldCheck size={16} /> View policies
                    </button>
                  </div>
                </section>
              )}
            </>
          )}

          {/* LINEAGE */}
          {activeSection === "lineage" && (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">PROVENANCE TRACKING</div>
                  <h1>Artifact lineage</h1>
                  <p>
                    Trace how an experiment connects to its inputs and outputs.
                  </p>
                </div>
              </div>

              <section className="panel">
                <div className="panel-header">
                  <div>
                    <h2>Lineage graph</h2>
                    <p>
                      {selected
                        ? `Selected experiment: ${selected.name}`
                        : "Select an experiment to inspect its lineage."}
                    </p>
                  </div>

                  <select
                    aria-label="Select experiment for lineage"
                    value={selected?.id ?? ""}
                    onChange={(event) =>
                      selectExperiment(Number(event.target.value))
                    }
                    disabled={experiments.length === 0}
                  >
                    {experiments.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </div>

                {selected ? (
                  <LineageGraph
                    lineage={lineageExperimentId === selected.id ? lineage : null}
                    loading={lineageLoading || lineageExperimentId !== selected.id}
                    error={lineageError}
                    onSelectNode={(node) => openEntityDetail(node.type, node)}
                    onPreviewArtifact={openArtifactDetail}
                  />
                ) : (
                  <div className="empty">
                    Create an experiment before viewing lineage.
                  </div>
                )}
              </section>
            </>
          )}

          {/* POLICY GATES */}
          {activeSection === "policies" && (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">QUALITY AND VALIDATION</div>
                  <h1>Policy gates</h1>
                  <p>
                    Review saved checks for the selected historical run.
                  </p>
                </div>
              </div>

              <section className="panel">
                <div className="panel-header">
                  <div>
                    <h2>
                      <ShieldCheck size={17} /> Validation results
                    </h2>
                    <p>
                      {selected
                        ? `${selected.name}${
                            selectedRun ? ` · Run #${selectedRun.id}` : ""
                          }`
                        : "Select an experiment and run to inspect its checks."}
                    </p>
                  </div>
                </div>

                {detailLoading || (selected && !currentExperimentDetail && !detailError) ? (
                  <div className="empty">Loading selected experiment…</div>
                ) : detailError ? (
                  <div className="empty error-text">
                    Could not load experiment details: {detailError}
                  </div>
                ) : selectedRun ? (
                  <>
                    {policiesLoading || policyRunId !== selectedRunId ? (
                      <div className="empty">Loading saved policy checks…</div>
                    ) : policiesError ? (
                      <div className="empty error-text">
                        Could not load policy checks: {policiesError}
                      </div>
                    ) : selectedRunPolicies.length ? (
                      <>
                      <PolicyResults checks={selectedRunPolicies} onSelectCheck={(check) => openEntityDetail("policy", { run_id: selectedRun.id, check })} />
                        <div className="policy-summary">
                          <span>Selected run: #{selectedRun.id}</span>
                          <strong
                            className={passCount === totalChecks ? "success" : "danger"}
                          >
                            {passCount}/{totalChecks} passed
                          </strong>
                        </div>
                      </>
                    ) : (
                      <div className="empty">
                        No policy checks are saved for run #{selectedRun.id}.
                      </div>
                    )}
                  </>
                ) : (
                  <>
                      <PolicyResults checks={[]} onSelectCheck={(check) => openEntityDetail("policy", { run_id: selectedRunId, check })} />
                    <div className="empty">
                      {selected
                        ? "This experiment has no runs yet. Run it to inspect policy checks."
                        : "Select or create an experiment to inspect policy checks."}
                    </div>
                  </>
                )}

                <div className="panel-actions">
                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => navigate("experiments")}
                  >
                    <Play size={16} /> Go to experiments
                  </button>
                </div>
              </section>
            </>
          )}

          {/* ARTIFACTS */}
          {activeSection === "artifacts" && (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">OUTPUT MANAGEMENT</div>
                  <h1>Artifacts</h1>
                  <p>
                    Browse generated outputs and their integrity checksums.
                  </p>
                </div>
              </div>

              <section className="panel">
                <div className="panel-header">
                  <div>
                    <h2>
                      <Archive size={17} /> Artifact registry
                    </h2>
                    <p>
                      Generated files recorded by experiment runs, with
                      SHA-256 checksums.
                    </p>
                  </div>
                  <span className="count-badge">
                    {artifacts.length} files
                  </span>
                </div>

                {artifacts.length === 0 ? (
                  <div className="empty">
                    No artifacts yet. Run an experiment to generate a result.
                  </div>
                ) : (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>ARTIFACT</th>
                          <th>RUN</th>
                          <th>SHA-256</th>
                          <th>SIZE</th>
                          <th>ACTION</th>
                        </tr>
                      </thead>
                      <tbody>
                        {artifacts.map((artifact) => (
                          <tr key={artifact.id}>
                            <td>
                              <Archive
                                size={15}
                                className="inline-icon"
                              />{" "}
                              <button type="button" className="text-button" onClick={() => openArtifactDetail(artifact)}>{artifact.name}</button>
                            </td>
                            <td><button type="button" className="text-button" onClick={() => openEntityDetail("run", { id: artifact.run_id })}>#{artifact.run_id}</button></td>
                            <td>
                              <code className="hash">
                                {artifact.sha256
                                  ? `${artifact.sha256.slice(0, 18)}…`
                                  : "—"}
                              </code>
                            </td>
                            <td>{artifact.size_bytes} B</td>
                            <td>
                              <a
                                className="button button-secondary"
                                href={`http://127.0.0.1:8000/api/artifacts/${artifact.id}/download`}
                                target="_blank"
                                rel="noreferrer"
                              >
                                Download
                              </a>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </>
          )}

          {activeSection === "comparison" && (
            <RunComparison
              experiments={experiments}
              selectedExperiment={selected}
              experimentDetail={currentExperimentDetail}
              detailLoading={detailLoading}
              detailError={detailError}
              onSelectExperiment={selectExperiment}
              registerRefreshHandler={registerScreenRefreshHandler}
              onInspectRun={(runId) => openEntityDetail("run", { id: runId })}
              onInspectComparison={openComparisonDetail}
            />
          )}

          {activeSection === "audit" && (
            <AuditTrail
              registerRefreshHandler={registerScreenRefreshHandler}
              onSelectEvent={(event) => openEntityDetail("audit", event)}
            />
          )}

          <footer>
            ResearchLab · Educational MVP · Runs locally on your machine
          </footer>
        </div>
      </main>

      {detailModal && (
        <EntityDetailModal
          title={detailTitle()}
          type={detailModal.type}
          onClose={closeEntityDetail}
        >
          {renderEntityContent()}
        </EntityDetailModal>
      )}

      {artifactPreview && (
        <ArtifactPreview
          artifact={artifactPreview}
          onClose={() => setArtifactPreview(null)}
        />
      )}

      {/* CREATE EXPERIMENT MODAL */}
      {showForm && (
        <div
          className="modal-backdrop"
          onClick={() => { setShowForm(false); setFormError(""); }}
        >
          <div
            className="modal"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-heading">
              <div>
                <h2>{editingExperimentId === null ? "Create experiment" : "Edit experiment"}</h2>
                <p>{editingExperimentId === null
                  ? "Register a new reproducible research run."
                  : "Update the saved definition used by future runs."}</p>
              </div>
              <button
                type="button"
                className="icon-button"
                onClick={() => { setShowForm(false); setFormError(""); }}
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={createExperiment}>
              <label>
                Experiment name
                <input
                  required
                  minLength="2"
                  maxLength="100"
                  value={form.name}
                  onChange={(event) =>
                    setForm({ ...form, name: event.target.value })
                  }
                />
              </label>

              <label>
                Description
                <textarea
                  rows="3"
                  value={form.description}
                  onChange={(event) =>
                    setForm({ ...form, description: event.target.value })
                  }
                />
              </label>

              <label>
                Parameters (JSON object)
                <textarea
                  rows="3"
                  spellCheck="false"
                  value={form.parameters}
                  onChange={(event) => {
                    setForm({ ...form, parameters: event.target.value });
                    setFormError("");
                  }}
                />
                <span className="muted small">
                  Saved parameters are available to your Python code as <code>parameters</code>, for example <code>parameters["seed"]</code>.
                </span>
              </label>

              <label>
                Python code
                <textarea
                  rows="8"
                  spellCheck="false"
                  value={form.customCode}
                  placeholder={'# Use input_data and assign your JSON output to result\nmarks = input_data["marks"]\nresult = {"average": sum(marks) / len(marks)}'}
                  onChange={(event) => {
                    setForm({ ...form, customCode: event.target.value });
                    setFormError("");
                  }}
                />
                <span className="muted small">
                  Save Python code before running. Assign a JSON-serializable value to <code>result</code>.
                </span>
              </label>

              <label>
                Input data (JSON object)
                <textarea
                  rows="5"
                  spellCheck="false"
                  value={form.inputData}
                  onChange={(event) => {
                    setForm({ ...form, inputData: event.target.value });
                    setFormError("");
                  }}
                />
                <span className="muted small">
                  Custom code reads this object as <code>input_data</code>. The random seed is available as <code>parameters["seed"]</code>. Maximum size: 1 MB.
                </span>
              </label>

              {formError && (
                <div className="form-error" role="alert">{formError}</div>
              )}

              <div className="modal-actions">
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => setShowForm(false)}
                >
                  Cancel
                </button>

                <button
                  type="submit"
                  className="button button-primary"
                  disabled={busy}
                >
                  {busy ? (
                    <LoaderCircle className="spin" size={16} />
                  ) : (
                    <Plus size={16} />
                  )}
                  {editingExperimentId === null ? "Create experiment" : "Save changes"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

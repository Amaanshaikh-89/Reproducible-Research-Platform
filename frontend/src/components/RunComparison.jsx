import React, { useCallback, useEffect, useMemo, useState } from "react";
import { GitCompareArrows, ShieldCheck } from "lucide-react";
import { api } from "../api";

function timeLabel(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function valueLabel(value) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function provenanceValue(field, side) {
  const value = field[side];
  if (field.field !== "artifact_sha256") return valueLabel(value);
  if (!Array.isArray(value) || !value.length) return "Not recorded";
  return value
    .map((artifact) => `${artifact.filename}: ${valueLabel(artifact.sha256)}`)
    .join("; ");
}

function RunSummary({ run, label, onInspectRun }) {
  if (!run) return null;
  return (
    <article className="comparison-run-card">
      <div className="comparison-run-heading">
        <strong>{label}</strong>
        {onInspectRun ? (
          <button type="button" className="text-button" onClick={() => onInspectRun(run.id)}>Run #{run.id}</button>
        ) : <span>Run #{run.id}</span>}
      </div>
      <div className="comparison-run-status">
        <span className={`pill ${run.status === "succeeded" ? "pill-success" : run.status === "failed" ? "pill-danger" : "pill-neutral"}`}>
          {run.status}
        </span>
      </div>
      <dl>
        <div><dt>Started</dt><dd>{timeLabel(run.started_at)}</dd></div>
        <div><dt>Completed</dt><dd>{timeLabel(run.finished_at)}</dd></div>
        <div className="comparison-message"><dt>Message</dt><dd>{run.message || "—"}</dd></div>
      </dl>
    </article>
  );
}

export default function RunComparison({
  experiments,
  selectedExperiment,
  experimentDetail,
  detailLoading,
  detailError,
  onSelectExperiment,
  registerRefreshHandler,
  onInspectRun,
  onInspectComparison,
}) {
  const [runAId, setRunAId] = useState("");
  const [runBId, setRunBId] = useState("");
  const [comparison, setComparison] = useState(null);
  const [comparing, setComparing] = useState(false);
  const [comparisonError, setComparisonError] = useState("");

  const runs = useMemo(
    () =>
      experimentDetail?.id === selectedExperiment?.id
        ? experimentDetail.runs || []
        : [],
    [experimentDetail, selectedExperiment?.id]
  );

  useEffect(() => {
    setComparisonError("");
    if (!runs.length) {
      setRunAId("");
      setRunBId("");
      return;
    }

    const available = new Set(runs.map((run) => String(run.id)));
    setRunAId((current) => (available.has(current) ? current : String(runs[0].id)));
    setRunBId((current) =>
      available.has(current)
        ? current
        : runs.length > 1
        ? String(runs[1].id)
        : ""
    );
  }, [runs, selectedExperiment?.id]);

  const runA = runs.find((run) => String(run.id) === runAId);
  const runB = runs.find((run) => String(run.id) === runBId);
  const invalidSelection = runA && runB && runA.id === runB.id;

  const refreshComparison = useCallback(async () => {
    if (!comparison) return;
    if (!runA || !runB || runA.id === runB.id) {
      setComparison(null);
      return;
    }

    setComparing(true);
    setComparisonError("");
    try {
      setComparison(await api.compareRuns(runA.id, runB.id));
    } catch (error) {
      setComparisonError(error.message);
      throw error;
    } finally {
      setComparing(false);
    }
  }, [comparison, runA, runB]);

  useEffect(() => {
    registerRefreshHandler?.(refreshComparison);
    return () => registerRefreshHandler?.(null);
  }, [refreshComparison, registerRefreshHandler]);

  useEffect(() => {
    if (!comparison) return;
    const availableRunIds = new Set(runs.map((run) => run.id));
    if (
      !availableRunIds.has(comparison.run_a?.id) ||
      !availableRunIds.has(comparison.run_b?.id)
    ) {
      setComparison(null);
    }
  }, [comparison, runs]);

  async function verifyComparison(event) {
    event.preventDefault();
    setComparison(null);
    setComparisonError("");
    if (!runA || !runB || runA.id === runB.id) {
      setComparisonError("Choose two different historical runs to compare.");
      return;
    }

    setComparing(true);
    try {
      const result = await api.compareRuns(runA.id, runB.id);
      setComparison(result);
    } catch (error) {
      setComparisonError(error.message);
    } finally {
      setComparing(false);
    }
  }

  const verdictClass =
    comparison?.verification.status === "MATCHED"
      ? "comparison-verdict-matched"
      : comparison?.verification.status === "DIFFERENT"
      ? "comparison-verdict-different"
      : "comparison-verdict-insufficient";

  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">REPRODUCIBILITY CHECK</div>
          <h1>Run comparison</h1>
          <p>Compare recorded outcomes and provenance without rerunning either experiment.</p>
        </div>
      </div>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2><GitCompareArrows size={17} /> Select historical runs</h2>
            <p>Runs from the selected experiment are loaded from saved history.</p>
          </div>
        </div>
        <form className="comparison-controls" onSubmit={verifyComparison}>
          <label>
            Experiment
            <select
              value={selectedExperiment?.id ?? ""}
              onChange={(event) => onSelectExperiment(Number(event.target.value))}
              disabled={!experiments.length}
            >
              {experiments.map((experiment) => (
                <option key={experiment.id} value={experiment.id}>
                  {experiment.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Run A
            <select
              value={runAId}
              onChange={(event) => {
                setRunAId(event.target.value);
                setComparison(null);
                setComparisonError("");
              }}
              disabled={detailLoading || runs.length === 0}
            >
              <option value="">Select a run</option>
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  Run #{run.id} · {run.status} · {timeLabel(run.started_at)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Run B
            <select
              value={runBId}
              onChange={(event) => {
                setRunBId(event.target.value);
                setComparison(null);
                setComparisonError("");
              }}
              disabled={detailLoading || runs.length < 2}
            >
              <option value="">Select a different run</option>
              {runs.map((run) => (
                <option key={run.id} value={run.id} disabled={String(run.id) === runAId}>
                  Run #{run.id} · {run.status} · {timeLabel(run.started_at)}
                </option>
              ))}
            </select>
          </label>
          <button
            className="button button-primary"
            type="submit"
            disabled={comparing || !runA || !runB || invalidSelection}
          >
            <ShieldCheck size={16} />
            {comparing ? "Verifying…" : "Compare and verify"}
          </button>
        </form>

        {detailLoading ? (
          <div className="empty" role="status">Loading run history…</div>
        ) : detailError ? (
          <div className="empty error-text" role="alert">Could not load run history: {detailError}</div>
        ) : !selectedExperiment ? (
          <div className="empty">Create an experiment before comparing runs.</div>
        ) : !runs.length ? (
          <div className="empty">This experiment has no run history yet.</div>
        ) : runs.length < 2 ? (
          <div className="empty">At least two historical runs are required for comparison.</div>
        ) : null}

        {comparisonError && (
          <div className="comparison-error" role="alert">{comparisonError}</div>
        )}
        {invalidSelection && (
          <div className="comparison-error" role="alert">
            Choose two different runs to compare.
          </div>
        )}
      </section>

      {comparison && (
        <>
          <section className="panel">
            <div className="panel-header">
              <div>
                <h2>Selected runs</h2>
                <p>Execution details and outcomes for both runs.</p>
              </div>
            </div>
            <div className="comparison-run-grid">
              <RunSummary run={comparison.run_a} label="Run A" onInspectRun={onInspectRun} />
              <RunSummary run={comparison.run_b} label="Run B" onInspectRun={onInspectRun} />
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>METRIC</th><th>RUN A</th><th>RUN B</th><th>DIFFERENCE (B − A)</th><th>COMPARABILITY</th></tr>
                </thead>
                <tbody>
                  {comparison.metrics.length ? comparison.metrics.map((metric) => (
                    <tr key={metric.name}>
                      <td>{onInspectComparison ? <button type="button" className="text-button" onClick={() => onInspectComparison({ label: metric.name.replaceAll("_", " "), metric, comparison })}>{metric.name.replaceAll("_", " ")}</button> : metric.name.replaceAll("_", " ")}</td>
                      <td>{valueLabel(metric.run_a)}</td>
                      <td>{valueLabel(metric.run_b)}</td>
                      <td>{metric.status === "COMPARABLE" ? valueLabel(metric.difference) : "—"}</td>
                      <td>{metric.status}</td>
                    </tr>
                  )) : (
                    <tr><td colSpan="5" className="empty">No metrics were recorded for either run.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel">
            <div className="panel-header">
              <div>
                <h2>Provenance comparison</h2>
                <p>Values are compared as recorded; missing historical metadata is not inferred.</p>
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>FIELD</th><th>RUN A</th><th>RUN B</th><th>RESULT</th></tr>
                </thead>
                <tbody>
                  {comparison.provenance.map((field) => (
                    <tr key={field.field}>
                      <td>{onInspectComparison ? <button type="button" className="text-button" onClick={() => onInspectComparison({ label: field.label, field, comparison })}>{field.label}</button> : field.label}</td>
                      <td className="comparison-value">{provenanceValue(field, "run_a")}</td>
                      <td className="comparison-value">{provenanceValue(field, "run_b")}</td>
                      <td>
                        <span className={`comparison-status comparison-status-${field.status.toLowerCase().replaceAll(" ", "-")}`}>
                          {field.status}
                        </span>
                        {field.field === "artifact_sha256" && field.pairs.length > 1 && (
                          <div className="comparison-artifact-pairs">
                            {field.pairs.map((pair) => (
                              <div key={`${pair.run_a_id}-${pair.run_b_id}-${pair.filename}`}>
                                {pair.filename}: {pair.status}
                              </div>
                            ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className={`comparison-verdict ${verdictClass}`}>
              <strong>{comparison.verification.status}</strong>
              {comparison.verification.reasons.map((reason) => <p key={reason}>{reason}</p>)}
            </div>
            <div className="comparison-disclaimer">
              Matching hashes support reproducibility but do not alone guarantee identical execution environments or outputs.
            </div>
          </section>
        </>
      )}
    </>
  );
}

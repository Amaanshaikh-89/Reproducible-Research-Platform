import React, { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { api } from "../api";
import ModalDialog from "./ModalDialog";

export default function ArtifactPreview({ artifact, onClose }) {
  const [preview, setPreview] = useState({
    loading: true,
    policyLoading: Boolean(artifact?.run_id),
    downloading: false,
    details: null,
    policies: [],
    error: "",
    policyError: "",
    downloadError: "",
  });

  useEffect(() => {
    let active = true;
    if (!artifact?.id) {
      setPreview((current) => ({
        ...current,
        loading: false,
        error: "This artifact does not include a registered artifact ID.",
      }));
      return () => { active = false; };
    }

    setPreview({
      loading: true,
      policyLoading: Boolean(artifact.run_id),
      downloading: false,
      details: null,
      policies: [],
      error: "",
      policyError: "",
      downloadError: "",
    });
    const requests = [api.previewArtifact(artifact.id)];
    if (artifact.run_id) requests.push(api.runPolicies(artifact.run_id));
    Promise.allSettled(requests).then(([previewResult, policyResult]) => {
      if (!active) return;
      setPreview((current) => ({
        ...current,
        loading: false,
        policyLoading: false,
        details: previewResult.status === "fulfilled" ? previewResult.value : null,
        error: previewResult.status === "rejected" ? previewResult.reason.message : "",
        policies: policyResult?.status === "fulfilled" ? policyResult.value : [],
        policyError: policyResult?.status === "rejected" ? policyResult.reason.message : "",
      }));
    });
    return () => { active = false; };
  }, [artifact?.id, artifact?.run_id]);

  async function downloadOriginal() {
    if (!artifact?.id) return;
    setPreview((current) => ({ ...current, downloading: true, downloadError: "" }));
    try {
      const blob = await api.downloadArtifact(artifact.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = preview.details?.filename || artifact.label || "artifact";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      setPreview((current) => ({ ...current, downloadError: error.message }));
    } finally {
      setPreview((current) => ({ ...current, downloading: false }));
    }
  }

  return (
    <ModalDialog
      title={preview.details?.filename || artifact?.label || "Artifact preview"}
      eyebrow="Artifact preview"
      onClose={onClose}
      headerClassName="artifact-preview-header"
      backdropClassName="artifact-preview-backdrop"
      dialogClassName="artifact-preview-dialog"
    >
      <div className="artifact-preview-subtitle">
        Artifact #{preview.details?.id ?? artifact?.id ?? "—"}
        {" · "}Run #{preview.details?.run_id ?? artifact?.run_id ?? "—"}
      </div>
      <div className="artifact-preview-actions">
        <button
          type="button"
          className="button button-secondary"
          onClick={downloadOriginal}
          disabled={preview.downloading || !preview.details}
        >
          <Download size={15} />
          {preview.downloading ? "Preparing download…" : "Download original"}
        </button>
        {preview.downloadError && <span className="error-text" role="alert">{preview.downloadError}</span>}
      </div>

      {preview.loading ? (
        <div className="empty" role="status">Loading artifact preview…</div>
      ) : preview.error ? (
        <div className="empty error-text" role="alert">Could not load artifact preview: {preview.error}</div>
      ) : preview.details && (
        <>
          <div className="artifact-preview-metadata">
            <div><strong>Integrity</strong><span className={`integrity-status integrity-${preview.details.integrity_status.toLowerCase().replaceAll(" ", "-")}`}>{preview.details.integrity_status}</span></div>
            <div><strong>Current size</strong><span>{preview.details.current_size_bytes} B</span></div>
            <div><strong>Recorded size</strong><span>{preview.details.stored_size_bytes} B</span></div>
            <div><strong>Created</strong><span>{preview.details.created_at ? new Date(preview.details.created_at).toLocaleString() : "Not recorded"}</span></div>
            <div><strong>Registered path</strong><span>{preview.details.relative_path}</span></div>
            <div><strong>Content type</strong><span>{preview.details.content_type}</span></div>
            <div className="artifact-hash"><strong>Stored SHA-256</strong><code>{preview.details.stored_sha256 || "Not recorded"}</code></div>
            <div className="artifact-hash"><strong>Current SHA-256</strong><code>{preview.details.current_sha256}</code></div>
          </div>
          {preview.details.integrity_status === "FAILED" && (
            <div className="artifact-integrity-warning" role="alert">
              The current file checksum does not match its stored checksum. This artifact is not verified.
            </div>
          )}
          <div className="artifact-policy-result">
            <strong>Saved artifact integrity check</strong>
            {preview.policyLoading ? (
              <span>Loading saved policy result…</span>
            ) : preview.policyError ? (
              <span className="error-text">Could not load saved policy check: {preview.policyError}</span>
            ) : (() => {
              const check = preview.policies.find((item) => item.policy_name === "artifact_integrity");
              return check ? (
                <span className={check.passed ? "success" : "danger"}>
                  {check.passed ? "PASS" : "FAIL"} — {check.message}
                </span>
              ) : <span>Not recorded for this run.</span>;
            })()}
          </div>
          <div className="artifact-json-viewer">
            {preview.details.content === null ? (
              <div className="empty">This artifact is not UTF-8 text and cannot be previewed here. Download it to inspect the original file.</div>
            ) : preview.details.content.length === 0 ? (
              <div className="empty">This artifact is empty.</div>
            ) : (() => {
              try {
                return <pre aria-label="Formatted JSON artifact content">{JSON.stringify(JSON.parse(preview.details.content), null, 2)}</pre>;
              } catch {
                return <><div className="artifact-content-note">Content is not valid JSON. Showing the file as plain text.</div><pre aria-label="Artifact content as plain text">{preview.details.content}</pre></>;
              }
            })()}
          </div>
        </>
      )}
    </ModalDialog>
  );
}

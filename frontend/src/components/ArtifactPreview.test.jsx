import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import ArtifactPreview from "./ArtifactPreview";

vi.mock("../api", () => ({ api: {
  previewArtifact: vi.fn(),
  runPolicies: vi.fn(),
  downloadArtifact: vi.fn(),
} }));

describe("ArtifactPreview", () => {
  beforeEach(() => {
    api.previewArtifact.mockResolvedValue({
      id: 12, run_id: 7, filename: "result.json", integrity_status: "VERIFIED",
      current_size_bytes: 12, stored_size_bytes: 12, created_at: null,
      relative_path: "artifacts/run-7/result.json", content_type: "application/json",
      stored_sha256: "abc", current_sha256: "abc", content: '{"ok":true}',
    });
    api.runPolicies.mockResolvedValue([{ policy_name: "artifact_integrity", passed: true, message: "Checksum matches." }]);
  });

  it("keeps preview metadata, saved integrity policy, and formatted artifact content", async () => {
    render(<ArtifactPreview artifact={{ id: 12, run_id: 7, label: "result.json" }} onClose={() => {}} />);
    expect(await screen.findByText("VERIFIED")).toBeInTheDocument();
    expect(screen.getByText(/Checksum matches\./)).toBeInTheDocument();
    expect(screen.getByLabelText("Formatted JSON artifact content")).toHaveTextContent('"ok": true');
    expect(api.previewArtifact).toHaveBeenCalledWith(12);
    expect(api.runPolicies).toHaveBeenCalledWith(7);
  });
});

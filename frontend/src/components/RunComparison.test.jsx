import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import RunComparison from "./RunComparison";

vi.mock("../api", () => ({ api: { compareRuns: vi.fn() } }));

describe("RunComparison detail interactions", () => {
  beforeEach(() => api.compareRuns.mockResolvedValue({
    run_a: { id: 7, status: "succeeded", started_at: null, finished_at: null, message: "ok" },
    run_b: { id: 8, status: "succeeded", started_at: null, finished_at: null, message: "ok" },
    metrics: [{ name: "accuracy", run_a: 0.8, run_b: 0.9, difference: 0.1, status: "COMPARABLE" }],
    provenance: [{ field: "configuration_sha256", label: "Configuration hash", run_a: "aaa", run_b: "bbb", status: "DIFFERENT" }],
    verification: { status: "DIFFERENT", reasons: ["Recorded values differ."] },
  }));

  it("opens actual run and comparison details from comparison results", async () => {
    const onInspectRun = vi.fn();
    const onInspectComparison = vi.fn();
    render(<RunComparison
      experiments={[{ id: 3, name: "Analysis" }]}
      selectedExperiment={{ id: 3, name: "Analysis" }}
      experimentDetail={{ id: 3, runs: [
        { id: 7, status: "succeeded", started_at: null, finished_at: null, message: "ok" },
        { id: 8, status: "succeeded", started_at: null, finished_at: null, message: "ok" },
      ] }}
      detailLoading={false}
      detailError=""
      onSelectExperiment={() => {}}
      onInspectRun={onInspectRun}
      onInspectComparison={onInspectComparison}
    />);

    fireEvent.click(screen.getByRole("button", { name: "Compare and verify" }));
    fireEvent.click(await screen.findByRole("button", { name: "Run #7" }));
    fireEvent.click(screen.getByRole("button", { name: "accuracy" }));
    fireEvent.click(screen.getByRole("button", { name: "Configuration hash" }));

    expect(onInspectRun).toHaveBeenCalledWith(7);
    expect(onInspectComparison).toHaveBeenNthCalledWith(1, expect.objectContaining({ metric: expect.objectContaining({ name: "accuracy" }) }));
    expect(onInspectComparison).toHaveBeenNthCalledWith(2, expect.objectContaining({ field: expect.objectContaining({ field: "configuration_sha256" }) }));
  });
});

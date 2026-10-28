import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LineageGraph from "./LineageGraph";

const lineage = {
  nodes: [
    { id: "dataset-1", type: "dataset", label: "input_data.json", run_id: 7 },
    { id: "code-1", type: "code", label: "custom_experiment.py", run_id: 7 },
    { id: "experiment-1", type: "experiment", label: "Analysis", experiment_id: 3 },
    { id: "run-1", type: "run", label: "Run #7 (succeeded)", run_id: 7 },
    { id: "artifact-1", type: "artifact", label: "result.json", artifact_id: 12 },
  ],
  edges: [],
};

describe("LineageGraph interactions", () => {
  it("activates every node with its own entity details or artifact preview action", () => {
    const onSelectNode = vi.fn();
    const onPreviewArtifact = vi.fn();
    render(<LineageGraph lineage={lineage} onSelectNode={onSelectNode} onPreviewArtifact={onPreviewArtifact} />);

    fireEvent.click(screen.getByRole("button", { name: /dataset: input_data.json/i }));
    fireEvent.click(screen.getByRole("button", { name: /code: custom_experiment.py/i }));
    fireEvent.click(screen.getByRole("button", { name: /experiment: analysis/i }));
    fireEvent.click(screen.getByRole("button", { name: /run: run #7/i }));
    fireEvent.click(screen.getByRole("button", { name: /artifact: result.json/i }));

    expect(onSelectNode.mock.calls.map(([node]) => node.type)).toEqual(["dataset", "code", "experiment", "run"]);
    expect(onPreviewArtifact).toHaveBeenCalledWith(lineage.nodes[4]);
  });

  it("supports keyboard activation for lineage nodes", () => {
    const onSelectNode = vi.fn();
    const { container } = render(<LineageGraph lineage={lineage} onSelectNode={onSelectNode} />);
    const dataset = container.querySelector(".node-dataset");
    dataset.focus();
    fireEvent.keyDown(dataset, { key: "Enter" });
    fireEvent.keyDown(dataset, { key: " " });
    expect(onSelectNode).toHaveBeenCalledTimes(2);
  });
});

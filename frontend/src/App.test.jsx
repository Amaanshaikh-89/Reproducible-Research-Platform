import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { api } from "./api";

vi.mock("./api", () => ({
  api: {
    experiments: vi.fn(),
    experiment: vi.fn(),
    artifacts: vi.fn(),
    health: vi.fn(),
    policies: vi.fn(),
    runPolicies: vi.fn(),
    lineage: vi.fn(),
    updateExperiment: vi.fn(),
  },
}));

const savedExperiment = {
  id: 17,
  name: "Saved custom calculation",
  description: "A saved definition to reopen",
  parameters: { seed: 81, threshold: 0.65, groups: ["a", "b"] },
  custom_code: 'result = {"answer": input_data["value"]}\n',
  input_data: { value: 42 },
  status: "created",
  created_at: "2026-01-01T00:00:00Z",
  last_run_id: null,
  runs: [],
};

describe("saved experiment editing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.experiments.mockResolvedValue([savedExperiment]);
    api.experiment.mockResolvedValue(savedExperiment);
    api.artifacts.mockResolvedValue([]);
    api.health.mockResolvedValue({ status: "healthy" });
    api.policies.mockResolvedValue([]);
    api.runPolicies.mockResolvedValue([]);
    api.lineage.mockResolvedValue({ nodes: [], edges: [] });
    api.updateExperiment.mockResolvedValue(savedExperiment);
  });

  it("reopens saved code, input, and all parameters for editing the existing record", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Experiments" }));
    await screen.findByRole("heading", { name: "Experiment registry" });
    await user.click(
      await screen.findByRole("button", {
        name: `Edit experiment ${savedExperiment.name}`,
      }),
    );

    expect(screen.getByLabelText("Experiment name")).toHaveValue(savedExperiment.name);
    expect(screen.getByLabelText("Description")).toHaveValue(savedExperiment.description);
    expect(JSON.parse(screen.getByLabelText(/Parameters \(JSON object\)/).value)).toEqual(
      savedExperiment.parameters,
    );
    expect(screen.getByPlaceholderText(/Use input_data/)).toHaveValue(savedExperiment.custom_code);
    expect(JSON.parse(screen.getByLabelText(/Input data \(JSON object\)/).value)).toEqual(
      savedExperiment.input_data,
    );

    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(api.updateExperiment).toHaveBeenCalledWith(
      savedExperiment.id,
      expect.objectContaining({
        name: savedExperiment.name,
        description: savedExperiment.description,
        parameters: savedExperiment.parameters,
        custom_code: savedExperiment.custom_code,
        input_data: savedExperiment.input_data,
      }),
    ));
  });
});

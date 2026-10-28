import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import PolicyResults from "./PolicyResults";

it("opens the selected saved policy result", () => {
  const onSelectCheck = vi.fn();
  const check = { id: 4, run_id: 7, policy_name: "artifact_integrity", passed: false, message: "Hash mismatch" };
  render(<PolicyResults checks={[check]} onSelectCheck={onSelectCheck} />);
  fireEvent.click(screen.getByRole("button", { name: "Inspect artifact integrity policy check" }));
  expect(onSelectCheck).toHaveBeenCalledWith(check);
});

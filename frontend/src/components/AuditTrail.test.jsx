import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import AuditTrail from "./AuditTrail";

vi.mock("../api", () => ({ api: { auditEvents: vi.fn() } }));

describe("AuditTrail interactions", () => {
  beforeEach(() => api.auditEvents.mockResolvedValue([{
    id: 21, event_type: "reproducibility_verification", occurred_at: "2026-01-01T00:00:00Z",
    run_a_id: 7, run_b_id: 8, result: "MATCHED",
  }]));

  it("opens the selected persisted event and reports load failures", async () => {
    const onSelectEvent = vi.fn();
    const { unmount } = render(<AuditTrail onSelectEvent={onSelectEvent} />);
    const eventButton = await screen.findByRole("button", { name: "Reproducibility verification" });
    fireEvent.click(eventButton);
    expect(onSelectEvent).toHaveBeenCalledWith(expect.objectContaining({ id: 21, run_a_id: 7 }));

    api.auditEvents.mockRejectedValueOnce(new Error("Audit service unavailable"));
    unmount();
    render(<AuditTrail onSelectEvent={onSelectEvent} />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Audit service unavailable"));
  });
});

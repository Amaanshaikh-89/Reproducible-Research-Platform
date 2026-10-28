import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ModalDialog from "./ModalDialog";

describe("ModalDialog", () => {
  it("closes on Escape and backdrop click, but not inside clicks", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<ModalDialog title="Run details" onClose={onClose}><button>Related run</button></ModalDialog>);

    await user.click(screen.getByRole("button", { name: "Related run" }));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.mouseDown(screen.getByRole("dialog").parentElement);
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("moves focus into the dialog and restores it when closed", () => {
    const trigger = document.createElement("button");
    document.body.appendChild(trigger);
    trigger.focus();
    const { unmount } = render(<ModalDialog title="Details" onClose={() => {}}>Content</ModalDialog>);
    expect(screen.getByRole("button", { name: "Close Details" })).toHaveFocus();
    unmount();
    expect(trigger).toHaveFocus();
    trigger.remove();
  });
});

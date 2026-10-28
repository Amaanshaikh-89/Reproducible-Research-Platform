import React from "react";
import ModalDialog from "./ModalDialog";

export default function EntityDetailModal({ title, type, onClose, children }) {
  return (
    <ModalDialog
      title={title}
      eyebrow={`${type} details`}
      onClose={onClose}
      backdropClassName="detail-modal-backdrop"
      dialogClassName="detail-modal"
    >
      <div className="detail-modal-content">{children}</div>
    </ModalDialog>
  );
}

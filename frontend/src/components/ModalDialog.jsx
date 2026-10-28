import React, { useEffect, useId, useRef } from "react";
import { X } from "lucide-react";

export default function ModalDialog({
  title,
  eyebrow = "DETAILS",
  onClose,
  children,
  headerClassName = "detail-modal-header",
  backdropClassName = "detail-modal-backdrop",
  dialogClassName = "detail-modal",
}) {
  const titleId = useId();
  const closeButtonRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const previousFocus = document.activeElement;
    closeButtonRef.current?.focus();

    function onKeyDown(event) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCloseRef.current?.();
        return;
      }
      if (event.key !== "Tab") return;

      const dialog = closeButtonRef.current?.closest('[role="dialog"]');
      const focusable = dialog
        ? [...dialog.querySelectorAll(
            'button:not(:disabled), a[href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])'
          )].filter((element) => element.getAttribute("aria-hidden") !== "true")
        : [];
      if (!focusable.length) {
        event.preventDefault();
        dialog?.focus();
      } else if (event.shiftKey && document.activeElement === focusable[0]) {
        event.preventDefault();
        focusable.at(-1)?.focus();
      } else if (!event.shiftKey && document.activeElement === focusable.at(-1)) {
        event.preventDefault();
        focusable[0]?.focus();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) {
        previousFocus.focus();
      }
    };
  }, []);

  return (
    <div
      className={backdropClassName}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose?.();
      }}
    >
      <section
        className={dialogClassName}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <header className={headerClassName}>
          <div>
            <span className="eyebrow">{eyebrow}</span>
            <h2 id={titleId}>{title}</h2>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            className="icon-button"
            aria-label={`Close ${title}`}
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}

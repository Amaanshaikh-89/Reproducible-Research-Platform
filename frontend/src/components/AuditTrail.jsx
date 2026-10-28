import React, { useCallback, useEffect, useRef, useState } from "react";
import { ClipboardList } from "lucide-react";
import { api } from "../api";

function timeLabel(value) {
  return value ? new Date(value).toLocaleString() : "—";
}

export default function AuditTrail({ registerRefreshHandler, onSelectEvent }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const loadingRef = useRef(false);

  const loadEvents = useCallback(async (throwOnError = false) => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setLoading(true);
    setError("");
    try {
      const latestEvents = await api.auditEvents();
      setEvents(latestEvents);
    } catch (loadError) {
      const message =
        loadError instanceof Error
          ? loadError.message
          : "An unexpected error occurred.";
      setError(
        message
      );
      if (throwOnError) throw loadError;
    } finally {
      loadingRef.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadEvents();
  }, [loadEvents]);

  useEffect(() => {
    registerRefreshHandler?.(() => loadEvents(true));
    return () => registerRefreshHandler?.(null);
  }, [loadEvents, registerRefreshHandler]);

  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">PERSISTED ACTIVITY</div>
          <h1>Audit trail</h1>
          <p>Report generation and reproducibility verification events recorded by this application.</p>
        </div>
      </div>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2><ClipboardList size={17} /> Recent audit events</h2>
            <p>Showing up to 100 newest events. The application exposes no edit or delete actions.</p>
          </div>
          <span className="count-badge">{events.length} events</span>
        </div>
        {loading && events.length === 0 ? (
          <div className="empty" role="status">Loading audit events…</div>
        ) : (
          <>
            {loading && (
              <div className="empty" role="status">Refreshing audit events…</div>
            )}
            {error && (
              <div className="empty error-text" role="alert">
                Could not load audit events: {error}
              </div>
            )}
            {!loading && !error && events.length === 0 ? (
              <div className="empty">
                No report or verification events have been recorded yet.
              </div>
            ) : events.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>TIME</th>
                      <th>EVENT</th>
                      <th>RUNS</th>
                      <th>RESULT</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.map((event) => (
                      <tr key={event.id} className={onSelectEvent ? "audit-event-row" : ""}>
                        <td className="muted small">{timeLabel(event.occurred_at)}</td>
                        <td>
                          {onSelectEvent ? (
                            <button type="button" className="text-button" onClick={() => onSelectEvent(event)}>
                              {event.event_type === "provenance_report_generated"
                                ? "Provenance report generated"
                                : "Reproducibility verification"}
                            </button>
                          ) : (
                            event.event_type === "provenance_report_generated"
                              ? "Provenance report generated"
                              : "Reproducibility verification"
                          )}
                        </td>
                        <td>
                          {event.run_a_id == null
                            ? "Run removed"
                            : `#${event.run_a_id}`}
                          {event.run_b_id == null
                            ? ""
                            : ` vs #${event.run_b_id}`}
                        </td>
                        <td>
                          <span
                            className={`comparison-status comparison-status-${String(
                              event.result ?? "unknown"
                            )
                              .toLowerCase()
                              .replaceAll(" ", "-")}`}
                          >
                            {event.result ?? "Unknown"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </>
        )}
        <div className="comparison-disclaimer">
          This is an application-level audit history, not tamper-proof or cryptographically immutable storage.
        </div>
      </section>
    </>
  );
}

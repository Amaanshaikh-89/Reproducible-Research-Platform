import React from "react";
import { CheckCircle2, XCircle, ShieldCheck } from "lucide-react";

export default function PolicyResults({ checks = [], onSelectCheck }) {
  if (!checks.length) return <div className="empty">Policy results appear after an experiment run.</div>;
  return <div className="policy-list">
    {checks.map((check) => {
      const Row = onSelectCheck ? "button" : "div";
      return <Row
        className={`policy-row${onSelectCheck ? " policy-row-action" : ""}`}
        key={check.id ?? `${check.run_id}-${check.policy_name}`}
        type={onSelectCheck ? "button" : undefined}
        onClick={onSelectCheck ? () => onSelectCheck(check) : undefined}
        aria-label={onSelectCheck ? `Inspect ${check.policy_name.replaceAll("_", " ")} policy check` : undefined}
      >
      {check.passed ? <CheckCircle2 className="success" size={19}/> : <XCircle className="danger" size={19}/>}
      <div className="policy-copy">
        <strong>{check.policy_name.replaceAll("_", " ")}</strong>
        <div className="muted small">{check.message}</div>
      </div>
      <span className={`pill ${check.passed ? "pill-success" : "pill-danger"}`}>{check.passed ? "PASS" : "FAIL"}</span>
      </Row>;
    })}
  </div>;
}

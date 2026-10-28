import React from "react";

export default function StatCard({ label, value, note, icon: Icon, onClick }) {
  const Tag = onClick ? "button" : "div";
  return <Tag
    className={`stat-card${onClick ? " stat-card-action" : ""}`}
    onClick={onClick}
    type={onClick ? "button" : undefined}
  >
    <div className="stat-top"><span>{label}</span>{Icon && <Icon size={18} />}</div>
    <div className="stat-value">{value}</div>
    <div className="muted small">{note}</div>
  </Tag>;
}

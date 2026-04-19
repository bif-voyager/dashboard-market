import type { ReactNode } from "react";

interface StatePanelProps {
  title: string;
  body: string;
  action?: ReactNode;
}

export function StatePanel({ title, body, action }: StatePanelProps) {
  return (
    <section className="state-panel">
      <h3>{title}</h3>
      <p>{body}</p>
      {action ? <div className="state-panel__action">{action}</div> : null}
    </section>
  );
}

import type { ReactNode } from "react";

interface StatusBannerProps {
  kind: "info" | "warning" | "error";
  children: ReactNode;
}

export function StatusBanner({ kind, children }: StatusBannerProps) {
  return <div className={`status-banner status-banner--${kind}`}>{children}</div>;
}

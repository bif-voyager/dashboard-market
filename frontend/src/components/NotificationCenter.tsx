import { useEffect, useMemo, useRef, useState } from "react";

export interface NotificationItem {
  id: string;
  kind: "info" | "warning" | "error";
  message: string;
}

interface NotificationCenterProps {
  notifications: NotificationItem[];
  title: string;
  emptyLabel: string;
  ariaLabel: string;
  floating?: boolean;
}

export function NotificationCenter({
  notifications,
  title,
  emptyLabel,
  ariaLabel,
  floating = false,
}: NotificationCenterProps) {
  const [open, setOpen] = useState(false);
  const [hasUnread, setHasUnread] = useState(false);
  const lastSeenSignature = useRef("");
  const signature = useMemo(() => notifications.map((item) => item.id).join("|"), [notifications]);

  useEffect(() => {
    if (!signature) {
      lastSeenSignature.current = "";
      setHasUnread(false);
      return;
    }
    if (open) {
      lastSeenSignature.current = signature;
      setHasUnread(false);
      return;
    }
    if (signature !== lastSeenSignature.current) {
      setHasUnread(true);
    }
  }, [open, signature]);

  function toggleOpen() {
    setOpen((current) => {
      const next = !current;
      if (next) {
        lastSeenSignature.current = signature;
        setHasUnread(false);
      }
      return next;
    });
  }

  return (
    <div className={floating ? "notification-center notification-center--floating" : "notification-center"}>
      <button
        className={open ? "notification-button notification-button--active" : "notification-button"}
        type="button"
        aria-label={ariaLabel}
        aria-expanded={open}
        onClick={toggleOpen}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" className="notification-button__icon">
          <path d="M12 22a2.6 2.6 0 0 0 2.45-1.75h-4.9A2.6 2.6 0 0 0 12 22Zm7-6.5-1.5-2.15V9a5.5 5.5 0 0 0-4.25-5.35V2.8a1.25 1.25 0 0 0-2.5 0v.85A5.5 5.5 0 0 0 6.5 9v4.35L5 15.5V18h14v-2.5Z" />
        </svg>
        {hasUnread ? <span className="notification-dot" aria-hidden="true" /> : null}
      </button>

      {open ? (
        <section className="notification-panel" aria-label={title}>
          <div className="notification-panel__header">
            <strong>{title}</strong>
            <span>{notifications.length}</span>
          </div>
          <div className="notification-list">
            {notifications.length ? (
              notifications.map((item) => (
                <article key={item.id} className={`notification-item notification-item--${item.kind}`}>
                  {item.message}
                </article>
              ))
            ) : (
              <p className="notification-empty">{emptyLabel}</p>
            )}
          </div>
        </section>
      ) : null}
    </div>
  );
}

import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import Icon from '../components/Icon';

const ToastContext = createContext(() => {});

const TOAST_MS = 5000;

/**
 * One transient confirmation at a time — "Copied", "Marked as reviewed" —
 * with an optional undo. Announced politely to screen readers.
 */
export function ToastProvider({ children }) {
  const [toast, setToast] = useState(null);
  const timer = useRef(null);

  const show = useCallback((message, { action, onAction, tone = 'default' } = {}) => {
    clearTimeout(timer.current);
    setToast({ message, action, onAction, tone, id: Date.now() });
    timer.current = setTimeout(() => setToast(null), TOAST_MS);
  }, []);

  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="toast-region" role="status" aria-live="polite">
        {toast && (
          <div className={`toast toast-${toast.tone}`} key={toast.id}>
            <Icon name={toast.tone === 'error' ? 'alert' : 'check-circle'} size={16} />
            <span>{toast.message}</span>
            {toast.action && (
              <button
                type="button"
                className="toast-action"
                onClick={() => {
                  toast.onAction?.();
                  setToast(null);
                }}
              >
                {toast.action}
              </button>
            )}
          </div>
        )}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

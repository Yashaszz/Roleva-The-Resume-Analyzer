/**
 * Toasts.
 *
 * Deliberately narrow in scope. A toast is for confirming something the user
 * just did ("Copied", "Analysis deleted") — never for reporting a failure they
 * need to act on. An error that vanishes after four seconds is an error the user
 * cannot read twice, and everything in Roleva that can fail already has a place
 * on the page to say so: the field's own error text, or the stream's error frame.
 *
 * `swipeDirection` and the viewport position are set for a thumb: bottom on a
 * phone, bottom-right on a desktop, never covering the primary action.
 */
"use client";

import * as ToastPrimitive from "@radix-ui/react-toast";
import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

type Toast = { id: number; message: string; tone: "neutral" | "good" };

const ToastContext = createContext<(message: string, tone?: Toast["tone"]) => void>(() => {});

/** `const toast = useToast(); toast("Copied")` */
export function useToast() {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const show = useCallback((message: string, tone: Toast["tone"] = "neutral") => {
    // Date.now() is enough of an id here: two toasts cannot be created in the
    // same millisecond by a human, and nothing persists them.
    setToasts((current) => [...current, { id: Date.now(), message, tone }]);
  }, []);

  const value = useMemo(() => show, [show]);

  return (
    <ToastContext.Provider value={value}>
      <ToastPrimitive.Provider swipeDirection="right" duration={4000}>
        {children}

        {toasts.map((toast) => (
          <ToastPrimitive.Root
            key={toast.id}
            onOpenChange={(open) => {
              if (!open) setToasts((current) => current.filter((t) => t.id !== toast.id));
            }}
            className={
              "bg-panel border rounded-sm px-4 py-3 flex items-center gap-2.5 " +
              "text-sm text-primary " +
              (toast.tone === "good" ? "border-shown" : "border-line-strong")
            }
          >
            {toast.tone === "good" ? (
              <svg
                width="15"
                height="15"
                viewBox="0 0 24 24"
                fill="none"
                stroke="var(--evidence-shown)"
                strokeWidth="2.2"
                aria-hidden="true"
                className="shrink-0"
              >
                <path d="M20 6 9 17l-5-5" />
              </svg>
            ) : null}
            <ToastPrimitive.Title>{toast.message}</ToastPrimitive.Title>
          </ToastPrimitive.Root>
        ))}

        <ToastPrimitive.Viewport
          className={
            "fixed z-50 flex flex-col gap-2 outline-none " +
            "bottom-4 left-4 right-4 " +
            "sm:left-auto sm:right-6 sm:bottom-6 sm:w-[340px]"
          }
        />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}

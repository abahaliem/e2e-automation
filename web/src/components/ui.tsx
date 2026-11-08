/* Komponen dasar bergaya shadcn/ui, disesuaikan dengan tema terang QA Agent. */
import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "outline" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-white font-semibold hover:bg-accent-hover disabled:bg-ink-600",
  outline: "border border-ink-600 bg-ink-900 text-fg hover:bg-ink-850 disabled:text-fg-dim",
  ghost: "text-fg-muted hover:bg-ink-850 hover:text-fg disabled:text-fg-dim",
  danger: "border border-fail/40 bg-ink-900 text-fail hover:bg-fail/5 disabled:opacity-50",
};
const SIZES: Record<Size, string> = { sm: "h-8 px-2.5 text-xs", md: "h-9 px-4 text-sm", lg: "h-11 px-6 text-sm" };

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }
>(function Button({ variant = "outline", size = "md", className, type = "button", ...props }, ref) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg transition-colors active:translate-y-px",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    />
  );
});

const fieldBase =
  "w-full rounded-lg border border-ink-600 bg-ink-900 px-3 text-sm text-fg placeholder:text-fg-dim focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15 disabled:bg-ink-850 aria-[invalid=true]:border-fail";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref,
) {
  return <input ref={ref} className={cn(fieldBase, "h-10", className)} {...props} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...props }, ref) {
    return <textarea ref={ref} className={cn(fieldBase, "py-2.5 leading-relaxed", className)} {...props} />;
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, ...props },
  ref,
) {
  return <select ref={ref} className={cn(fieldBase, "h-10 pr-8", className)} {...props} />;
});

export function Field({
  label,
  htmlFor,
  hint,
  error,
  children,
  className,
}: {
  label: string;
  htmlFor: string;
  hint?: ReactNode;
  error?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={htmlFor} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {error ? (
        <p role="alert" className="text-xs text-fail">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-fg-muted">{hint}</p>
      ) : null}
    </div>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  id,
  description,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  id: string;
  description?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        {description && <p className="mt-0.5 text-xs text-fg-muted">{description}</p>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative h-6 w-10 shrink-0 rounded-full p-0 transition-colors",
          checked ? "bg-accent" : "bg-ink-600",
        )}
      >
        <span
          className={cn(
            "absolute left-0 top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform",
            checked ? "translate-x-[18px]" : "translate-x-0.5",
          )}
        />
      </button>
    </div>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("rounded-xl border border-ink-700 bg-ink-900", className)}>{children}</div>;
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-fg-muted">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-3">{actions}</div>}
    </header>
  );
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
      <div className="font-medium">{title}</div>
      {description && <p className="max-w-[48ch] text-sm text-fg-muted">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} aria-hidden />;
}

export function Alert({
  tone = "info",
  children,
  action,
}: {
  tone?: "info" | "warning" | "error" | "success";
  children: ReactNode;
  action?: ReactNode;
}) {
  const tones = {
    info: "border-accent-line bg-accent-soft text-fg",
    warning: "border-review/40 bg-review/5 text-fg",
    error: "border-fail/40 bg-fail/5 text-fg",
    success: "border-pass/40 bg-pass/5 text-fg",
  };
  return (
    <div role={tone === "error" || tone === "warning" ? "alert" : "status"} className={cn("flex items-center gap-3 rounded-lg border px-4 py-3 text-sm", tones[tone])}>
      <div className="flex-1">{children}</div>
      {action}
    </div>
  );
}

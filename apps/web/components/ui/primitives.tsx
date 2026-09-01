"use client";

/**
 * The small set of primitives the interface is built from.
 *
 * Hand-written rather than pulled from a component library: the app needs
 * about six of them, and a bespoke set keeps the visual language coherent and
 * the dependency surface small.
 */

import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

import { cx } from "@/lib/utils";

type ButtonVariant = "primary" | "secondary" | "ghost" | "subtle" | "danger";
type ButtonSize = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: ReactNode;
}

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 px-2.5 text-[13px] gap-1.5 rounded-[8px]",
  md: "h-9.5 px-4 text-sm gap-2 rounded-[10px]",
  lg: "h-12 px-6 text-[15px] gap-2.5 rounded-[12px]",
};

const VARIANTS: Record<ButtonVariant, React.CSSProperties> = {
  primary: {
    background: "var(--accent)",
    color: "var(--accent-contrast)",
    boxShadow: "var(--shadow-soft)",
  },
  secondary: {
    background: "var(--surface)",
    color: "var(--text)",
    borderColor: "var(--border-strong)",
    boxShadow: "var(--shadow-soft)",
  },
  subtle: {
    background: "var(--surface-sunken)",
    color: "var(--text-secondary)",
    borderColor: "transparent",
  },
  ghost: { background: "transparent", color: "var(--text-secondary)" },
  danger: { background: "transparent", color: "var(--danger)" },
};

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  icon,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(
        "inline-flex items-center justify-center font-medium whitespace-nowrap select-none",
        "transition-[transform,box-shadow,background-color,color,border-color] duration-150",
        "disabled:pointer-events-none disabled:opacity-45",
        "active:translate-y-px",
        variant === "secondary" && "border hover:border-[var(--text-faint)]",
        variant === "primary" && "hover:brightness-[1.07]",
        (variant === "ghost" || variant === "danger" || variant === "subtle") &&
          "hover:bg-[var(--surface-sunken)]",
        SIZES[size],
        className,
      )}
      style={VARIANTS[variant]}
    >
      {loading ? <Spinner /> : icon}
      {children}
    </button>
  );
}

/** Icon-only button with a required accessible name. */
export function IconButton({
  label,
  icon,
  active = false,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string;
  icon: ReactNode;
  active?: boolean;
}) {
  return (
    <button
      {...rest}
      aria-label={label}
      title={label}
      className={cx(
        "inline-flex h-8 w-8 items-center justify-center rounded-[9px]",
        "transition-colors duration-150 hover:bg-[var(--surface-sunken)]",
        "disabled:pointer-events-none disabled:opacity-40",
        className,
      )}
      style={{
        color: active ? "var(--accent)" : "var(--text-muted)",
        background: active ? "var(--accent-subtle)" : undefined,
      }}
    >
      {icon}
    </button>
  );
}

export function Spinner({ size = 14 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
      className="animate-spin"
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeWidth="2.5"
        opacity="0.22"
      />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

type Tone = "neutral" | "accent" | "success" | "warning" | "danger";

const TONES: Record<Tone, React.CSSProperties> = {
  neutral: {
    background: "var(--surface-sunken)",
    color: "var(--text-muted)",
    borderColor: "var(--border)",
  },
  accent: {
    background: "var(--accent-subtle)",
    color: "var(--accent)",
    borderColor: "var(--accent-border)",
  },
  success: {
    background: "var(--success-subtle)",
    color: "var(--success)",
    borderColor: "transparent",
  },
  warning: {
    background: "var(--warning-subtle)",
    color: "var(--warning)",
    borderColor: "transparent",
  },
  danger: {
    background: "var(--danger-subtle)",
    color: "var(--danger)",
    borderColor: "transparent",
  },
};

export function Badge({
  tone = "neutral",
  children,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-[var(--radius-pill)] border",
        "px-2 py-0.5 text-[11px] font-medium whitespace-nowrap",
        className,
      )}
      style={TONES[tone]}
    >
      {children}
    </span>
  );
}

export function Card({
  className,
  style,
  ...rest
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      {...rest}
      className={cx("rounded-[var(--radius-card)] border", className)}
      style={{
        background: "var(--surface)",
        borderColor: "var(--border)",
        boxShadow: "var(--shadow-soft)",
        ...style,
      }}
    />
  );
}

/** Monospace format tag shown beside a filename, e.g. PDF / DOCX. */
export function FormatTag({ label }: { label: string }) {
  return (
    <span
      className="inline-flex h-6 shrink-0 items-center justify-center rounded-[6px] px-1.5 font-mono text-[10px] font-semibold tracking-wider"
      style={{
        background: "var(--surface-sunken)",
        color: "var(--text-muted)",
      }}
    >
      {label}
    </span>
  );
}

/** Segmented control used for view switching. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
  size = "md",
}: {
  options: Array<{ value: T; label: string; icon?: ReactNode }>;
  value: T;
  onChange: (value: T) => void;
  label: string;
  size?: "sm" | "md";
}) {
  return (
    <div
      role="tablist"
      aria-label={label}
      className="inline-flex items-center gap-0.5 rounded-[10px] p-0.5"
      style={{ background: "var(--surface-sunken)" }}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(option.value)}
            className={cx(
              "inline-flex items-center gap-1.5 rounded-[8px] font-medium",
              "transition-all duration-150",
              size === "sm" ? "h-6.5 px-2.5 text-[12px]" : "h-7.5 px-3 text-[13px]",
            )}
            style={
              active
                ? {
                    background: "var(--surface)",
                    color: "var(--text)",
                    boxShadow: "var(--shadow-soft)",
                  }
                : { color: "var(--text-muted)" }
            }
          >
            {option.icon}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

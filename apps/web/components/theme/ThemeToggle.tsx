"use client";

import { Monitor, Moon, Sun } from "lucide-react";

import { cx } from "@/lib/utils";
import { useTheme, type Theme } from "./ThemeProvider";

const OPTIONS: Array<{ value: Theme; label: string; Icon: typeof Sun }> = [
  { value: "light", label: "Light", Icon: Sun },
  { value: "system", label: "System", Icon: Monitor },
  { value: "dark", label: "Dark", Icon: Moon },
];

/**
 * Segmented light / system / dark control.
 *
 * Three states rather than a switch, because "follow the system" is a real
 * preference that a two-state toggle cannot express.
 */
export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="inline-flex items-center gap-0.5 rounded-[10px] p-0.5"
      style={{ background: "var(--surface-sunken)" }}
    >
      {OPTIONS.map(({ value, label, Icon }) => {
        const active = theme === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={`${label} theme`}
            title={`${label} theme`}
            onClick={() => setTheme(value)}
            className={cx(
              "flex h-7 w-7 items-center justify-center rounded-[8px]",
              "transition-all duration-150",
              !active && "hover:text-[var(--text-secondary)]",
            )}
            style={
              active
                ? {
                    background: "var(--surface)",
                    color: "var(--text)",
                    boxShadow: "var(--shadow-soft)",
                  }
                : { color: "var(--text-faint)" }
            }
          >
            <Icon size={14} aria-hidden strokeWidth={2} />
          </button>
        );
      })}
    </div>
  );
}

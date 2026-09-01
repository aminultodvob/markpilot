/**
 * The MarkPilot mark.
 *
 * A paper-plane nose formed out of a document corner: the "pilot" idea and the
 * "document" idea in one shape, rather than a plane sitting next to a page.
 */
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <span
      className="relative inline-flex shrink-0 items-center justify-center"
      style={{
        width: size,
        height: size,
        borderRadius: size * 0.3,
        background: "var(--accent)",
        color: "var(--accent-contrast)",
        boxShadow: "var(--shadow-soft)",
      }}
      aria-hidden
    >
      <svg
        width={size * 0.6}
        height={size * 0.6}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {/* Flight path, sweeping up from the lower left. */}
        <path d="M3 17.5c3.4 0 5.6-1.6 7.2-3.6" opacity="0.5" />
        {/* The plane: a folded sheet seen from above. */}
        <path d="M20.5 4.2 12.6 20a.55.55 0 0 1-1-.06l-1.7-5.3-5.3-1.7a.55.55 0 0 1-.06-1z" />
      </svg>
    </span>
  );
}

/** Wordmark used in the header and footer. */
export function Wordmark({ size = 28 }: { size?: number }) {
  return (
    <span className="flex items-center gap-2.5">
      <Logo size={size} />
      <span
        className="text-[15px] font-semibold tracking-[-0.01em]"
        style={{ color: "var(--text)" }}
      >
        MarkPilot
      </span>
    </span>
  );
}

import Link from 'next/link';

/**
 * An answer bubble whose last line ends in a footnote spark: "every answer has a source".
 * Colours come from the --logo-* tokens in globals.css, so it follows the theme.
 */
export function LogoMark({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" aria-hidden="true" className="shrink-0">
      <path
        d="M28 16H92a20 20 0 0 1 20 20V74a20 20 0 0 1-20 20H52L32 108V94H28A20 20 0 0 1 8 74V36A20 20 0 0 1 28 16Z"
        fill="var(--logo-tile)"
        stroke="var(--logo-tile-line)"
        strokeWidth="2"
      />
      <path d="M30 40H90M30 56H80M30 72H58" fill="none" stroke="var(--logo-line)" strokeWidth="8" strokeLinecap="round" />
      <path d="M77 61Q77 72 88 72Q77 72 77 83Q77 72 66 72Q77 72 77 61Z" fill="var(--logo-spark)" />
    </svg>
  );
}

/** The mark and the BekenAI wordmark; `size` is the mark's size. */
export function Logo({
  href = '/',
  size = 26,
  className = '',
  label = 'BekenAI',
}: {
  href?: string;
  size?: number;
  className?: string;
  /** The link's accessible name, in the interface language. */
  label?: string;
}) {
  return (
    <Link
      href={href}
      className={`flex items-center no-underline ${className}`}
      style={{ gap: Math.round(size * 0.3) }}
      aria-label={label}
    >
      <LogoMark size={size} />
      <span
        className="font-bold leading-none tracking-[-0.02em] text-[var(--logo-word)]"
        style={{ fontSize: Math.round(size * 0.66) }}
      >
        Beken<span className="text-[var(--logo-ai)]">AI</span>
      </span>
    </Link>
  );
}

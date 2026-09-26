import Link from 'next/link';

/** Text lines ending in a citation dot: "every answer has a source". */
export function LogoMark({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="shrink-0">
      <rect width="32" height="32" rx="8" fill="var(--inv)" />
      <path d="M9 11h14M9 16h10M9 21h6" fill="none" stroke="var(--inv-fg)" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="21.5" cy="21" r="2.6" fill="var(--dot)" />
    </svg>
  );
}

export function Logo({ href = '/', size = 26 }: { href?: string; size?: number }) {
  return (
    <Link href={href} className="flex items-center gap-2.5 text-fg no-underline" aria-label="BekenAI ana sayfa">
      <LogoMark size={size} />
      <span className="text-[15px] font-semibold tracking-[-0.01em]">BekenAI</span>
    </Link>
  );
}

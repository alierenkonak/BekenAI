import Image from 'next/image';
import Link from 'next/link';

// The logo comes in two colourings: dark ink for the light theme and the original cream for
// the dark one. Both are rendered and globals.css hides the one that does not match
// `data-theme` (a media query cannot see the user's theme choice). The hidden one is lazy,
// so it is never downloaded.
const LOGO_RATIO = 382 / 144;

function ThemedImage({
  name,
  width,
  height,
  alt,
  className = '',
}: {
  name: 'logo' | 'mark';
  width: number;
  height: number;
  alt: string;
  className?: string;
}) {
  return (
    <>
      {(['light', 'dark'] as const).map((theme) => (
        <Image
          key={theme}
          src={`/brand/${name}-${theme}.png`}
          width={width}
          height={height}
          alt={alt}
          unoptimized
          className={`theme-${theme} shrink-0 ${className}`}
        />
      ))}
    </>
  );
}

/** The emblem alone, where the name is written beside it or space is tight. */
export function LogoMark({ size = 26 }: { size?: number }) {
  return <ThemedImage name="mark" width={size} height={size} alt="" />;
}

/** The full logo, emblem and name; it is drawn about one and a half times `size` tall. */
export function Logo({ href = '/', size = 26, className = '' }: { href?: string; size?: number; className?: string }) {
  const height = Math.round(size * 1.55);
  return (
    <Link href={href} className={`flex items-center no-underline ${className}`} aria-label="BekenAI ana sayfa">
      <ThemedImage name="logo" width={Math.round(height * LOGO_RATIO)} height={height} alt="BekenAI" />
    </Link>
  );
}

import type { Metadata, Viewport } from 'next';
import { Geist, Geist_Mono, Instrument_Serif } from 'next/font/google';
import { THEME_STORAGE_KEY } from '@/lib/theme-key';
import './globals.css';

const geist = Geist({ variable: '--font-geist', subsets: ['latin', 'latin-ext'] });
const geistMono = Geist_Mono({ variable: '--font-geist-mono', subsets: ['latin', 'latin-ext'] });
const instrumentSerif = Instrument_Serif({
  variable: '--font-instrument-serif',
  subsets: ['latin', 'latin-ext'],
  weight: '400',
  style: ['normal', 'italic'],
});

export const metadata: Metadata = {
  title: {
    default: 'BekenAI — Kaynağı belli hukuki cevaplar',
    template: '%s · BekenAI',
  },
  description:
    'Türk iş hukuku için kaynağa dayalı yapay zekâ araştırması: hibrit arama, iddia bazlı doğrulama ve sürümlü kaynak kaydı. Demo proje.',
  icons: { icon: '/favicon.png', apple: '/apple-icon.png' },
};

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#fcfcfb' },
    { media: '(prefers-color-scheme: dark)', color: '#0e0e10' },
  ],
};

// Runs before first paint so the stored or system theme never flashes.
const themeScript = `(function(){try{var t=localStorage.getItem('${THEME_STORAGE_KEY}');if(t!=='light'&&t!=='dark'){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}document.documentElement.setAttribute('data-theme',t)}catch(e){}})()`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="tr"
      data-theme="light"
      suppressHydrationWarning
      className={`${geist.variable} ${geistMono.variable} ${instrumentSerif.variable}`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-dvh bg-bg text-fg antialiased">{children}</body>
    </html>
  );
}

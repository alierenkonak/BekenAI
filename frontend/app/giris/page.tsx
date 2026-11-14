import type { Metadata } from 'next';
import Link from 'next/link';
import { Logo } from '@/components/brand';
import { Icon } from '@/components/icons';
import { LocaleToggle } from '@/components/locale-toggle';
import { ThemeToggle } from '@/components/theme-toggle';
import { rich } from '@/lib/i18n/rich';
import { getI18n } from '@/lib/i18n/server';

export async function generateMetadata(): Promise<Metadata> {
  return { title: 'Under maintenance' };
}

export default async function SignInPage() {
  const { locale, m } = await getI18n();
  const t = m.signIn;
  return (
    <div className="grid min-h-dvh grid-cols-1 lg:grid-cols-[680px_minmax(0,1fr)]">
      <section className="hidden flex-col justify-between border-r border-line bg-side px-16 py-10 lg:flex">
        <Logo size={34} label={m.common.homeLabel} />
        <div className="flex flex-col gap-9">
          <h1 className="m-0 font-serif text-[60px] font-normal leading-[1.02] tracking-[-0.015em]">
            {t.titleLine}
            <br />
            {rich(t.titleRest, { em: <span className="italic">{t.titleEm}</span> })}
          </h1>
          {/* The sample stays in Turkish in both languages: it is what BekenAI actually writes. */}
          <div lang="tr" className="flex w-[500px] flex-col gap-2.5 rounded-[14px] border border-line bg-surface px-5 py-[18px] shadow-soft">
            <p className="m-0 text-[14.5px] leading-relaxed">
              Bildirim şartına uymayan işveren, bildirim süresine ilişkin ücret tutarında ihbar tazminatı öder.
              <span className="ml-1 inline-flex h-[19px] min-w-5 items-center justify-center rounded-[5px] bg-accent px-[5px] align-[1px] font-mono text-[11px] font-medium text-inv-fg">
                1
              </span>
            </p>
            <div className="flex flex-col gap-1.5 rounded-[10px] bg-muted px-3.5 py-3">
              <span lang={locale} className="text-xs font-medium text-fg3">
                {t.sampleSource}
              </span>
              <span className="text-[13px] leading-normal text-fg2">
                <mark className="rounded-[3px] bg-mark px-0.5 text-fg">
                  Bildirim şartına uymayan taraf, bildirim süresine ilişkin ücret tutarında tazminat ödemek zorundadır.
                </mark>
              </span>
            </div>
            <span lang={locale} className="flex items-center gap-1.5 text-xs font-medium text-ok">
              <Icon name="shieldCheck" size={13} strokeWidth={2} />
              {t.sampleVerified}
            </span>
          </div>
          <ul className="m-0 flex list-none flex-col gap-2.5 p-0 text-[14.5px] text-fg2">
            {t.points.map((point) => (
              <li key={point} className="flex items-center gap-2.5">
                <Icon name="check" strokeWidth={2} className="text-fg" />
                {point}
              </li>
            ))}
          </ul>
        </div>
        <span className="text-[12.5px] text-fg3">{t.footer}</span>
      </section>

      <section className="relative flex items-center justify-center px-6 py-16">
        <div className="absolute right-5 top-5 flex items-center gap-2">
          <LocaleToggle />
          <ThemeToggle />
        </div>
        <div className="flex w-full max-w-[380px] flex-col gap-7">
          <div className="lg:hidden">
            <Logo size={34} label={m.common.homeLabel} />
          </div>
          <div lang="en" className="flex flex-col gap-7">
            <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.12em] text-fg3">
              <span aria-hidden="true" className="h-2 w-2 rounded-full bg-doc" />
              Temporarily unavailable
            </div>
            <div className="flex flex-col gap-3">
              <h2 className="m-0 font-serif text-[38px] font-normal leading-tight tracking-[-0.02em]">
                We’re under maintenance.
              </h2>
              <p className="m-0 text-[14.5px] leading-relaxed text-fg2">
                BekenAI is temporarily offline while we work on restoring the service.
                Sign-in and the live demo are unavailable during this time.
              </p>
            </div>
            <div className="rounded-[12px] border border-line bg-side px-4 py-3.5">
              <p className="m-0 text-xs font-medium text-fg3">Maintenance started</p>
              <time dateTime="2026-11-15" className="mt-1 block text-[14.5px] font-medium text-fg">
                15 November 2026
              </time>
            </div>
            <p className="m-0 text-[13px] leading-relaxed text-fg3">
              Thank you for your patience. Please check back later.
            </p>
            <Link href="/" className="flex h-[46px] items-center justify-center gap-2.5 rounded-[10px] border border-line-strong bg-surface text-[14.5px] font-medium text-fg shadow-soft transition-colors hover:bg-hover">
              Back to home
              <span aria-hidden="true">↗</span>
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}

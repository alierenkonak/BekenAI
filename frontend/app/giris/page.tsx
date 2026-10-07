import type { Metadata } from 'next';
import { Logo } from '@/components/brand';
import { Icon } from '@/components/icons';
import { LocaleToggle } from '@/components/locale-toggle';
import { ThemeToggle } from '@/components/theme-toggle';
import { rich } from '@/lib/i18n/rich';
import { getI18n } from '@/lib/i18n/server';
import { SignInPanel } from './sign-in-panel';

export async function generateMetadata(): Promise<Metadata> {
  const { m } = await getI18n();
  return { title: m.meta.signIn };
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
          <SignInPanel />
        </div>
      </section>
    </div>
  );
}

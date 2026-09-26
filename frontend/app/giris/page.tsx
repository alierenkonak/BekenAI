import type { Metadata } from 'next';
import { Logo } from '@/components/brand';
import { Icon } from '@/components/icons';
import { ThemeToggle } from '@/components/theme-toggle';
import { SignInPanel } from './sign-in-panel';

export const metadata: Metadata = { title: 'Giriş' };

const POINTS = [
  'Mevzuat, Yargıtay kararları ve doktrin tek yerde',
  'Her iddia, dayandığı pasajla ayrıca doğrulanır',
  'Desteklenmeyen iddia cevaba hiç girmez',
];

export default function SignInPage() {
  return (
    <div className="grid min-h-dvh grid-cols-1 lg:grid-cols-[680px_minmax(0,1fr)]">
      <section className="hidden flex-col justify-between border-r border-line bg-side px-16 py-10 lg:flex">
        <Logo size={28} />
        <div className="flex flex-col gap-9">
          <h1 className="m-0 font-serif text-[60px] font-normal leading-[1.02] tracking-[-0.015em]">
            Her cevabın arkasında
            <br />
            bir <span className="italic">kaynak</span> var.
          </h1>
          <div className="flex w-[500px] flex-col gap-2.5 rounded-[14px] border border-line bg-surface px-5 py-[18px] shadow-soft">
            <p className="m-0 text-[14.5px] leading-relaxed">
              Bildirim şartına uymayan işveren, bildirim süresine ilişkin ücret tutarında ihbar tazminatı öder.
              <span className="ml-1 inline-flex h-[19px] min-w-5 items-center justify-center rounded-[5px] bg-accent px-[5px] align-[1px] font-mono text-[11px] font-medium text-inv-fg">
                1
              </span>
            </p>
            <div className="flex flex-col gap-1.5 rounded-[10px] bg-muted px-3.5 py-3">
              <span className="text-xs font-medium text-fg3">4857 sayılı İş Kanunu · Madde 17</span>
              <span className="text-[13px] leading-normal text-fg2">
                <mark className="rounded-[3px] bg-mark px-0.5 text-fg">
                  Bildirim şartına uymayan taraf, bildirim süresine ilişkin ücret tutarında tazminat ödemek zorundadır.
                </mark>
              </span>
            </div>
            <span className="flex items-center gap-1.5 text-xs font-medium text-ok">
              <Icon name="shieldCheck" size={13} strokeWidth={2} />
              İddia kaynak pasajıyla doğrulandı
            </span>
          </div>
          <ul className="m-0 flex list-none flex-col gap-2.5 p-0 text-[14.5px] text-fg2">
            {POINTS.map((point) => (
              <li key={point} className="flex items-center gap-2.5">
                <Icon name="check" strokeWidth={2} className="text-fg" />
                {point}
              </li>
            ))}
          </ul>
        </div>
        <span className="text-[12.5px] text-fg3">© 2026 BekenAI · Demo proje</span>
      </section>

      <section className="relative flex items-center justify-center px-6 py-16">
        <div className="absolute right-5 top-5 flex items-center gap-3">
          <ThemeToggle />
        </div>
        <div className="flex w-full max-w-[380px] flex-col gap-7">
          <div className="lg:hidden">
            <Logo size={28} />
          </div>
          <SignInPanel />
        </div>
      </section>
    </div>
  );
}

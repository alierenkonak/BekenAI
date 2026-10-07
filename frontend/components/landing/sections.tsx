import Link from 'next/link';
import type { ReactNode } from 'react';
import { Logo } from '@/components/brand';
import { Icon } from '@/components/icons';
import { LocaleToggle } from '@/components/locale-toggle';
import { ThemeToggle } from '@/components/theme-toggle';
import { SectionLabel } from '@/components/ui';
import { GITHUB_URL, LINKEDIN_URL } from '@/lib/config';
import { SAMPLE_FILE_URL } from '@/lib/files';
import { rich } from '@/lib/i18n/rich';
import type { LandingContent } from './content';
import { HeroAnimation } from './hero-animation';
import { PipelineAnimation } from './pipeline-animation';

const container = 'mx-auto w-full max-w-[1312px] px-4 sm:px-6 lg:px-8';

function SerifHeading({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <h2 className={`m-0 font-serif text-[40px] font-normal leading-[1.02] tracking-[-0.015em] sm:text-[54px] ${className}`}>
      {children}
    </h2>
  );
}

function SectionHead({ label, title, lead }: { label: string; title: ReactNode; lead?: string }) {
  return (
    <div className="flex flex-col justify-between gap-6 md:flex-row md:items-end md:gap-12">
      <div className="flex flex-col gap-3.5">
        <SectionLabel>{label}</SectionLabel>
        <SerifHeading>{title}</SerifHeading>
      </div>
      {lead && <p className="m-0 max-w-[460px] text-base leading-relaxed text-fg2">{lead}</p>}
    </div>
  );
}

type Section = { c: LandingContent };

export function DemoBar({ c }: Section) {
  return (
    <div className="flex min-h-10 flex-wrap items-center justify-center gap-x-2.5 gap-y-1 border-b border-line bg-side px-4 py-2 text-center text-[13px] text-fg2">
      <span className="flex h-5 items-center rounded-full bg-doc-bg px-2 text-[11.5px] font-semibold text-doc">{c.demoBar.badge}</span>
      <span>{c.demoBar.text}</span>
      <a href="#demo" className="font-medium text-fg no-underline hover:underline">
        {c.demoBar.link}
      </a>
    </div>
  );
}

export function SiteHeader({ c }: Section) {
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur">
      <div className={`${container} flex h-[72px] items-center gap-3 md:gap-9`}>
        <Logo size={34} label={c.nav.home} />
        <nav aria-label={c.nav.label} className="hidden gap-7 text-sm md:flex">
          <a href="#nasil" className="text-fg2 no-underline hover:text-fg">{c.nav.how}</a>
          <a href="#mimari" className="text-fg2 no-underline hover:text-fg">{c.nav.architecture}</a>
          <a href="#teknoloji" className="text-fg2 no-underline hover:text-fg">{c.nav.tech}</a>
          <a href="#sss" className="text-fg2 no-underline hover:text-fg">{c.nav.faq}</a>
        </nav>
        <span className="grow" />
        {GITHUB_URL && (
          <a href={GITHUB_URL} className="hidden items-center gap-1.5 text-sm font-medium text-fg no-underline sm:flex" rel="noreferrer" target="_blank">
            <Icon name="code" strokeWidth={1.9} />
            GitHub
          </a>
        )}
        <span className="flex items-center gap-2">
          <LocaleToggle />
          <ThemeToggle />
        </span>
        <Link href="/giris" className="flex h-[38px] items-center whitespace-nowrap rounded-[9px] bg-inv px-4 text-sm font-medium text-inv-fg no-underline">
          {c.nav.tryDemo}
        </Link>
      </div>
    </header>
  );
}

export function Hero({ c }: Section) {
  return (
    <section className={`${container} grid grid-cols-1 items-center gap-12 py-14 lg:pb-28 lg:pt-[72px] xl:grid-cols-[minmax(0,1fr)_600px] xl:gap-16 2xl:grid-cols-[minmax(0,1fr)_640px]`}>
      <div className="flex flex-col gap-7">
        <h1 className="m-0 font-serif text-[52px] font-normal leading-[0.98] tracking-[-0.02em] sm:text-[68px] xl:text-[80px]">
          {rich(c.hero.title, { em: <span className="italic">{c.hero.titleEm}</span> })}
        </h1>
        <p className="m-0 max-w-[520px] text-lg leading-relaxed text-fg2">{c.hero.lead}</p>
        {c.hero.languageNote && (
          <p className="m-0 flex max-w-[520px] items-start gap-2 text-[13.5px] leading-normal text-fg3">
            <Icon name="globe" size={15} className="mt-0.5 shrink-0" />
            {c.hero.languageNote}
          </p>
        )}
        <div className="flex flex-wrap gap-3">
          <Link href="/giris" className="flex h-[46px] items-center gap-2 rounded-[10px] bg-inv px-5 text-[15px] font-medium text-inv-fg no-underline">
            {c.nav.tryDemo}
            <Icon name="arrowRight" strokeWidth={2} />
          </Link>
          <a href="#mimari" className="flex h-[46px] items-center rounded-[10px] border border-line-strong px-5 text-[15px] font-medium text-fg no-underline hover:bg-surface">
            {c.hero.explore}
          </a>
        </div>
        <ul className="m-0 flex list-none flex-wrap gap-x-5 gap-y-2 p-0 pt-3 text-[13.5px] text-fg2">
          {c.hero.facts.map((fact) => (
            <li key={fact} className="flex items-center gap-1.5">
              <Icon name="check" size={14} strokeWidth={2.2} className="text-ok" />
              {fact}
            </li>
          ))}
        </ul>
      </div>
      <HeroAnimation />
    </section>
  );
}

export function TechWall({ c }: Section) {
  return (
    <section id="teknoloji" className={`${container} flex scroll-mt-24 flex-col items-center gap-7 pb-32`}>
      <SectionLabel>{c.techLabel}</SectionLabel>
      <ul className="m-0 grid w-full list-none grid-cols-2 gap-px overflow-hidden rounded-[18px] border border-line bg-line p-0 sm:grid-cols-3 lg:grid-cols-6">
        {c.tech.map(([name, role]) => (
          <li key={name} className="flex h-[104px] flex-col items-center justify-center gap-1.5 bg-side px-3 text-center">
            <span className="text-base font-semibold tracking-[-0.01em]">{name}</span>
            <span className="text-[12.5px] text-fg3">{role}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Vignette({ children }: { children: ReactNode }) {
  return (
    <div aria-hidden="true" className="flex h-60 flex-col justify-center gap-2.5 border-b border-line bg-side px-6 py-7 sm:px-9">
      {children}
    </div>
  );
}

function FeatureCard({ vignette, title, body }: { vignette: ReactNode; title: string; body: string }) {
  return (
    <article className="flex flex-col overflow-hidden rounded-[18px] border border-line bg-surface">
      {vignette}
      <div className="flex flex-col gap-2 px-8 pb-8 pt-6">
        <h3 className="m-0 text-[19px] font-semibold tracking-[-0.01em]">{title}</h3>
        <p className="m-0 text-[15px] leading-relaxed text-fg2">{body}</p>
      </div>
    </article>
  );
}

export function HowItWorks({ c }: Section) {
  const t = c.how;
  return (
    <section id="nasil" className={`${container} flex scroll-mt-24 flex-col gap-12 pb-36`}>
      <SectionHead
        label={t.label}
        title={<>{t.titleLine}<br />{t.titleRest}</>}
        lead={t.lead}
      />
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        <FeatureCard
          title={t.search.title}
          body={t.search.body}
          vignette={
            <Vignette>
              <div lang="tr" className="flex h-[38px] items-center gap-2 rounded-[10px] border border-line-strong bg-surface px-3 text-[13.5px]">
                <Icon name="search" size={15} className="text-fg3" />
                ihbar süresi bildirim şartı
              </div>
              {t.search.results.map(([title, tags], index) => (
                <div key={title} className={`flex h-9 items-center gap-3 rounded-lg px-3 text-[13px] ${index === 0 ? 'bg-surface' : ''}`}>
                  <span className="font-mono text-[11.5px] text-fg3">{String(index + 1).padStart(2, '0')}</span>
                  <span className="grow truncate font-medium">{title}</span>
                  <span className="font-mono text-[11px] text-fg3">{tags}</span>
                </div>
              ))}
              <span className="font-mono text-[11px] text-fg3">{t.search.flow}</span>
            </Vignette>
          }
        />
        <FeatureCard
          title={t.write.title}
          body={t.write.body}
          vignette={
            <Vignette>
              <div className="flex w-fit flex-col gap-0.5 self-center rounded-[10px] border border-line bg-surface px-3 py-2 shadow-soft">
                <span className="text-[12.5px] font-semibold">{t.write.source}</span>
                <span className="text-[11.5px] text-fg3">{t.write.article}</span>
              </div>
              <p lang="tr" className="m-0 text-base leading-relaxed">
                Bildirim şartına uymayan işveren, bildirim süresine ilişkin ücret tutarında ihbar tazminatı öder.
                <span className="ml-1 inline-flex h-[19px] min-w-5 items-center justify-center rounded-[5px] bg-accent px-[5px] align-[1px] font-mono text-[11px] font-medium text-inv-fg">1</span>
                <span className="ml-1 inline-flex h-[19px] min-w-5 items-center justify-center rounded-[5px] border border-accent-line bg-accent-bg px-[5px] align-[1px] font-mono text-[11px] font-medium text-accent">2</span>
              </p>
            </Vignette>
          }
        />
        <FeatureCard
          title={t.verify.title}
          body={t.verify.body}
          vignette={
            <Vignette>
              {[
                ['Bildirim süresi sekiz haftadır.', t.verify.supported, 'border-transparent bg-ok-bg text-ok', false],
                ['Kıdem tazminatı her tam yıl için 30 günlük ücrettir.', t.verify.partial, 'border-dashed border-accent text-accent', false],
                ['İşveren ayrıca kötüniyet tazminatı öder.', t.verify.unverified, 'border-dashed border-err-line text-err', true],
              ].map(([text, badge, tone, flagged]) => (
                <div key={String(text)} className="flex h-12 items-center gap-3 rounded-[10px] border border-line bg-surface px-3.5">
                  <span
                    lang="tr"
                    className={`grow truncate text-[13.5px] ${flagged ? 'underline decoration-err/70 decoration-dashed decoration-1 underline-offset-[5px]' : ''}`}
                  >
                    {text}
                  </span>
                  <span className={`flex h-[22px] shrink-0 items-center rounded-full border px-2 text-[11.5px] font-medium ${tone}`}>{badge}</span>
                </div>
              ))}
            </Vignette>
          }
        />
        <FeatureCard
          title={t.passage.title}
          body={t.passage.body}
          vignette={
            <Vignette>
              <div className="flex flex-wrap items-center gap-2">
                <span className="flex h-[22px] items-center rounded-md bg-accent-bg px-2 text-xs font-medium text-accent">{t.passage.kind}</span>
                <span className="text-sm font-semibold">{t.passage.source}</span>
                <span className="text-xs text-fg3">{t.passage.article}</span>
              </div>
              <div lang="tr" className="rounded-[10px] border border-line bg-surface px-3.5 py-3 text-[13px] leading-relaxed text-fg2">
                Bu süreler asgari olup sözleşmeler ile artırılabilir.{' '}
                <mark className="rounded-[3px] bg-mark px-0.5 text-fg">
                  Bildirim şartına uymayan taraf, bildirim süresine ilişkin ücret tutarında tazminat ödemek zorundadır.
                </mark>
              </div>
              <span className="flex h-[22px] w-fit items-center rounded-full bg-ok-bg px-2 text-[11.5px] font-medium text-ok">{t.passage.supports}</span>
            </Vignette>
          }
        />
      </div>
    </section>
  );
}

function SubHead({ n, title, note }: { n: string; title: string; note?: string }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3.5 gap-y-1">
      <span className="font-mono text-[12.5px] text-accent">{n}</span>
      <h3 className="m-0 grow text-2xl font-semibold tracking-[-0.015em]">{title}</h3>
      {note && <span className="text-[13px] text-fg3">{note}</span>}
    </div>
  );
}

const PHASE_TONE = {
  search: 'bg-accent-bg text-accent',
  select: 'bg-accent-bg text-accent',
  write: 'bg-muted text-fg2',
  verify: 'bg-ok-bg text-ok',
} as const;

const PHASE_TEXT = {
  search: 'text-accent',
  select: 'text-accent',
  write: 'text-fg2',
  verify: 'text-ok',
} as const;

export function Architecture({ c }: Section) {
  const t = c.architecture;
  return (
    <section id="mimari" className="scroll-mt-24 border-t border-line bg-side">
      <div className={`${container} flex flex-col gap-[72px] pb-36 pt-[104px]`}>
        <div className="flex flex-col gap-9">
          <div className="grid grid-cols-1 items-end gap-6 md:grid-cols-2 md:gap-16">
            <div className="flex flex-col gap-3.5">
              <SectionLabel>{t.label}</SectionLabel>
              <SerifHeading>{t.title}</SerifHeading>
            </div>
            <p className="m-0 text-[17px] leading-relaxed text-fg2">
              {rich(t.lead, { rag: <strong className="font-semibold text-fg">RAG</strong> })}
            </p>
          </div>
          <dl className="m-0 grid grid-cols-2 overflow-hidden rounded-2xl border border-line bg-surface lg:grid-cols-4">
            {t.metrics.map(([value, label], index) => (
              <div
                key={value}
                className={`flex flex-col gap-1.5 px-6 py-5 ${index % 2 === 0 ? 'border-r border-line' : ''} ${index < 2 ? 'border-b border-line lg:border-b-0' : ''} ${index === 1 ? 'lg:border-r' : ''}`}
              >
                <dt className="font-serif text-[46px] leading-none tracking-[-0.01em]">{value}</dt>
                <dd className="m-0 text-[13.5px] leading-snug text-fg2">{label}</dd>
              </div>
            ))}
          </dl>
        </div>

        <div className="flex flex-col gap-6">
          <SubHead n="01" title={t.ragTitle} />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.75fr)]">
            <div className="flex flex-col gap-4">
              {t.approaches.map((approach) => (
                <div key={approach.title} className="flex grow flex-col gap-3.5 rounded-2xl border border-line bg-surface p-6">
                  <h4 className="m-0 text-[17px] font-semibold">{approach.title}</h4>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {approach.flow.map((item, index) => (
                      <span key={item} className="flex items-center gap-1.5">
                        <span className="flex h-[26px] items-center rounded-[7px] bg-muted px-2.5 text-[12.5px] font-medium text-fg2">{item}</span>
                        {index < approach.flow.length - 1 && <span aria-hidden="true" className="text-xs text-fg3">→</span>}
                      </span>
                    ))}
                  </div>
                  <p className="m-0 text-[14.5px] leading-relaxed text-fg2">{approach.body}</p>
                  <div className={`mt-auto flex items-center gap-2 border-t border-line pt-3 text-[13px] font-medium ${approach.tone === 'err' ? 'text-err' : 'text-fg2'}`}>
                    <span className={`size-[7px] rounded-full ${approach.tone === 'err' ? 'bg-err' : 'bg-fg2'}`} />
                    {approach.verdict}
                  </div>
                </div>
              ))}
            </div>
            <div className="flex flex-col gap-[18px] rounded-2xl border border-accent bg-surface px-7 py-[26px]">
              <div className="flex items-center gap-2.5">
                <h4 className="m-0 grow text-[19px] font-semibold tracking-[-0.01em]">{t.oursTitle}</h4>
                <span className="flex h-[22px] items-center rounded-full bg-accent-bg px-2 text-[11.5px] font-semibold text-accent">BekenAI</span>
              </div>
              <p className="m-0 text-[14.5px] leading-relaxed text-fg2">{t.oursBody}</p>
              <ol className="m-0 grid list-none grid-cols-1 gap-x-7 p-0 md:grid-flow-col md:grid-cols-2 md:grid-rows-5">
                {t.ourSteps.map((step, index) => (
                  <li key={step.title} className="flex gap-3 border-t border-line py-3">
                    <span className={`flex size-6 shrink-0 items-center justify-center rounded-[7px] font-mono text-[11.5px] font-medium ${PHASE_TONE[step.phase]}`}>
                      {index + 1}
                    </span>
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className="flex items-center gap-2">
                        <span className="text-sm font-semibold">{step.title}</span>
                        <span className={`font-mono text-[10.5px] ${PHASE_TEXT[step.phase]}`}>{t.phases[step.phase]}</span>
                      </span>
                      <span className="text-[13px] leading-normal text-fg2">{step.body}</span>
                    </span>
                  </li>
                ))}
              </ol>
              <div className="mt-auto flex items-center gap-2 border-t border-line pt-3 text-[13px] font-medium text-ok">
                <span className="size-[7px] rounded-full bg-ok" />
                {t.oursVerdict}
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-6">
          <SubHead n="02" title={t.pipelineTitle} note={t.pipelineNote} />
          <PipelineAnimation />
          {(['preparation', 'question'] as const).map((phase) => (
            <div key={phase} className="flex flex-col gap-3">
              <h4 className="m-0 flex items-center gap-2 text-[11.5px] font-semibold tracking-[0.12em] text-fg3">
                {phase === 'preparation' ? t.preparation : t.everyQuestion}
                <span className="h-px grow bg-line" />
              </h4>
              {/* Each card spans two rows of a shared grid (subgrid), so the cards in a row line up:
                  their descriptions end, and their technical parts begin, at the same height. */}
              <ol
                className={`m-0 grid list-none grid-cols-1 gap-4 p-0 md:grid-cols-2 ${phase === 'preparation' ? 'lg:grid-cols-3' : 'xl:grid-cols-4'}`}
              >
                {t.pipeline.map((step, index) => ({ step, index }))
                  .filter(({ step }) => step.phase === phase)
                  .map(({ step, index }) => (
                    <li
                      key={step.en}
                      className="row-span-2 grid grid-rows-subgrid gap-0 overflow-hidden rounded-2xl border border-line bg-surface"
                    >
                      <div className="flex flex-col gap-2.5 px-6 pb-5 pt-[22px]">
                        <div className="flex items-center gap-2.5">
                          <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-accent-bg font-mono text-xs font-medium text-accent">
                            {index + 1}
                          </span>
                          <h4 className="m-0 grow text-[17px] font-semibold">{step.title}</h4>
                        </div>
                        <span className="font-mono text-[11px] text-fg3">{step.en}</span>
                        <p className="m-0 text-[15px] leading-relaxed">{step.plain}</p>
                      </div>
                      <div className="flex flex-col gap-2.5 border-t border-line bg-bg px-6 pb-5 pt-4">
                        <span className="text-[11px] font-semibold tracking-[0.14em] text-fg3">{t.technical}</span>
                        <p className="m-0 text-[13.5px] leading-relaxed text-fg2">{step.tech}</p>
                        <div className="mt-auto flex flex-wrap gap-1.5">
                          {step.tags.map((tag) => (
                            <span key={tag} className="flex h-[22px] items-center rounded-md border border-line px-2 font-mono text-[11px] text-fg2">
                              {tag}
                            </span>
                          ))}
                        </div>
                      </div>
                    </li>
                  ))}
              </ol>
            </div>
          ))}
        </div>

        <div className="flex flex-col gap-6">
          <SubHead n="03" title={t.journeyTitle} note={t.journeyNote} />
          <ol className="m-0 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {t.journey.map((item, index) => (
              <li key={item.title} className="flex flex-col gap-3">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-accent">{index + 1}</span>
                  <span className="h-px grow bg-line-strong" />
                  {index < t.journey.length - 1 && <Icon name="chevRight" size={10} strokeWidth={2.5} className="text-fg3" />}
                </div>
                <div className="flex grow flex-col gap-2 rounded-[14px] border border-line bg-surface p-[18px] xl:h-[214px]">
                  <span className="text-xs font-medium text-fg3">{item.where}</span>
                  <h4 className="m-0 text-base font-semibold">{item.title}</h4>
                  <p className="m-0 text-[13.5px] leading-normal text-fg2">{item.body}</p>
                  <span className="mt-auto font-mono text-[11px] leading-normal text-fg3">{item.tech}</span>
                </div>
              </li>
            ))}
          </ol>
          <div className="flex flex-wrap items-center gap-x-[18px] gap-y-2 rounded-xl border border-dashed border-line-strong px-[18px] py-3.5 text-[13px] text-fg2">
            <span className="text-xs font-semibold tracking-[0.12em] text-fg3">{t.infrastructure}</span>
            <span><span className="font-semibold text-fg">Supabase</span> Auth · PostgreSQL · Storage</span>
            <span className="text-fg3">/</span>
            <span><span className="font-semibold text-fg">Oracle Cloud</span> {t.infraVm}</span>
            <span className="text-fg3">/</span>
            <span>{t.infraPrivate}</span>
          </div>
        </div>

        <div className="flex flex-col gap-6">
          <SubHead n="04" title={t.decisionsTitle} note={t.decisionsNote} />
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {t.adrs.map((adr) => (
              <div key={adr.id} className="flex flex-col gap-2 rounded-2xl border border-line bg-surface px-6 py-[22px]">
                <span className="font-mono text-[11.5px] text-fg3">{adr.id}</span>
                <h4 className="m-0 text-[17px] font-semibold tracking-[-0.01em]">{adr.title}</h4>
                <p className="m-0 text-sm leading-relaxed text-fg2">{adr.body}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-5">
          <SubHead n="05" title={t.glossaryTitle} note={t.glossaryNote} />
          <dl className="m-0 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {t.glossary.map(([term, definition]) => (
              <div key={term} className="flex flex-col gap-2 rounded-[14px] border border-line bg-surface p-[18px]">
                <dt className="text-[15px] font-semibold">{term}</dt>
                <dd className="m-0 text-[13.5px] leading-normal text-fg2">{definition}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </section>
  );
}

export function Coverage({ c }: Section) {
  return (
    <section id="kapsam" className={`${container} flex scroll-mt-24 flex-col gap-10 pb-36 pt-[120px]`}>
      <SectionHead label={c.coverage.label} title={c.coverage.title} lead={c.coverage.lead} />
      <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
        {c.coverage.groups.map((group) => (
          <div key={group.title} className="flex flex-col gap-4 rounded-[18px] border border-line bg-surface px-7 py-[26px]">
            <div className="flex items-center gap-2.5">
              <span className={`size-2.5 rounded-[3px] ${group.tone}`} />
              <h3 className="m-0 text-[17px] font-semibold">{group.title}</h3>
            </div>
            <ul className="m-0 flex list-none flex-col p-0">
              {group.items.map((item) => (
                <li key={item} className="border-t border-line py-[11px] text-[15px]">{item}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

export function Security({ c }: Section) {
  return (
    <section className={`${container} flex flex-col gap-10 pb-36`}>
      <div className="flex flex-col gap-3.5">
        <SectionLabel>{c.security.label}</SectionLabel>
        <SerifHeading>{c.security.title}</SerifHeading>
      </div>
      <ul className="m-0 grid list-none grid-cols-1 gap-px overflow-hidden rounded-[18px] border border-line bg-line p-0 md:grid-cols-3">
        {c.security.items.map((item) => (
          <li key={item.title} className="flex flex-col gap-2.5 bg-surface p-7">
            <Icon name={item.icon} size={20} strokeWidth={1.7} />
            <h3 className="m-0 text-base font-semibold">{item.title}</h3>
            <p className="m-0 text-sm leading-relaxed text-fg2">{item.body}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function DemoNote({ c }: Section) {
  const t = c.demo;
  return (
    <section id="demo" className={`${container} scroll-mt-24 pb-36`}>
      <div className="grid grid-cols-1 gap-10 rounded-[22px] border border-doc-line bg-surface px-6 py-10 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] md:gap-14 md:px-14 md:py-12">
        <div className="flex flex-col gap-[18px]">
          <span className="flex h-6 w-fit items-center rounded-full bg-doc-bg px-2.5 text-xs font-semibold text-doc">{t.badge}</span>
          <h2 className="m-0 font-serif text-[38px] font-normal leading-[1.04] tracking-[-0.015em] sm:text-[46px]">{t.title}</h2>
          <p className="m-0 text-base leading-relaxed text-fg2">{t.body}</p>
          <div className="flex flex-wrap items-center gap-3.5 pt-2.5">
            <span className="flex size-11 items-center justify-center rounded-full bg-accent-bg text-sm font-semibold text-accent">AK</span>
            <div className="flex grow flex-col">
              <span className="text-[15px] font-semibold">Ali Eren Konak</span>
              <span className="text-[13px] text-fg3">{t.role}</span>
            </div>
            {GITHUB_URL && (
              <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="flex h-10 items-center gap-1.5 rounded-[10px] bg-inv px-3.5 text-sm font-medium text-inv-fg no-underline">
                <Icon name="code" size={15} strokeWidth={1.9} />
                {t.github}
              </a>
            )}
            {LINKEDIN_URL && (
              <a href={LINKEDIN_URL} target="_blank" rel="noreferrer" className="flex h-10 items-center rounded-[10px] border border-line-strong px-3.5 text-sm font-medium text-fg no-underline">
                LinkedIn
              </a>
            )}
          </div>
          <a
            href={SAMPLE_FILE_URL}
            download
            className="flex w-fit items-center gap-2 rounded-[10px] border border-dashed border-file-line bg-file-bg px-3.5 py-2.5 text-sm text-file no-underline"
          >
            <Icon name="download" size={15} />
            <span>
              <span className="font-medium">{t.sample}</span>
              <span className="text-fg2">{t.sampleNote}</span>
            </span>
          </a>
        </div>
        <div className="flex flex-col gap-3.5">
          <h3 className="m-0 text-[15px] font-semibold">{t.limitsTitle}</h3>
          <ul className="m-0 flex list-none flex-col p-0">
            {t.limits.map((limit, index) => (
              <li key={limit} className="flex gap-3 border-t border-line py-3.5 text-[14.5px] leading-normal text-fg2">
                <span className="shrink-0 pt-0.5 font-mono text-xs text-fg3">{String(index + 1).padStart(2, '0')}</span>
                {limit}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

export function Faq({ c }: Section) {
  return (
    <section id="sss" className={`${container} grid scroll-mt-24 grid-cols-1 gap-10 pb-36 md:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)] md:gap-20`}>
      <div className="flex flex-col gap-3.5">
        <SectionLabel>{c.faq.label}</SectionLabel>
        <SerifHeading>{c.faq.title}</SerifHeading>
      </div>
      <div className="flex flex-col border-t border-line">
        {c.faq.items.map((item, index) => (
          <details key={item.q} open={index === 0} className="group border-b border-line">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-4 py-5 text-[17px] font-medium">
              {item.q}
              <Icon name="plus" size={18} className="text-fg3 transition-transform group-open:rotate-45" />
            </summary>
            <p className="m-0 pb-[22px] pr-10 text-[15px] leading-relaxed text-fg2">{item.a}</p>
          </details>
        ))}
      </div>
    </section>
  );
}

export function FinalCta({ c }: Section) {
  return (
    <section className={`${container} pb-28`}>
      <div className="flex flex-col items-center gap-6 rounded-[22px] bg-inv px-6 py-[72px] text-center text-inv-fg">
        <h2 className="m-0 font-serif text-[40px] font-normal leading-[1.02] tracking-[-0.015em] sm:text-[58px]">{c.cta.title}</h2>
        <p className="m-0 max-w-[520px] text-base leading-relaxed opacity-75">{c.cta.body}</p>
        <Link href="/giris" className="flex h-[46px] items-center gap-2 rounded-[10px] bg-inv-fg px-5 text-[15px] font-medium text-inv no-underline">
          {c.nav.tryDemo}
          <Icon name="arrowRight" strokeWidth={2} />
        </Link>
      </div>
    </section>
  );
}

export function SiteFooter({ c }: Section) {
  return (
    <footer className="border-t border-line">
      <div className={`${container} flex flex-wrap items-center gap-x-7 gap-y-3 pb-10 pt-8 text-[13px] text-fg3`}>
        <Logo size={28} label={c.nav.home} />
        <span>{c.footer.copyright}</span>
        <span className="grow">{c.footer.disclaimer}</span>
        <a href="#mimari" className="text-fg2 no-underline hover:text-fg">{c.nav.architecture}</a>
        {GITHUB_URL && (
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="text-fg2 no-underline hover:text-fg">GitHub</a>
        )}
      </div>
    </footer>
  );
}

import {
  Architecture,
  Coverage,
  DemoNote,
  Faq,
  FinalCta,
  Hero,
  HowItWorks,
  Security,
  SiteFooter,
  SiteHeader,
  TechWall,
} from '@/components/landing/sections';
import { LANDING } from '@/components/landing/content';
import { getLocale } from '@/lib/i18n/server';

export default async function LandingPage() {
  const c = LANDING[await getLocale()];
  return (
    <>
      <SiteHeader c={c} />
      <main>
        <Hero c={c} />
        <TechWall c={c} />
        <HowItWorks c={c} />
        <Architecture c={c} />
        <Coverage c={c} />
        <Security c={c} />
        <DemoNote c={c} />
        <Faq c={c} />
        <FinalCta c={c} />
      </main>
      <SiteFooter c={c} />
    </>
  );
}

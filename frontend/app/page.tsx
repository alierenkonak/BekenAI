import {
  Architecture,
  Coverage,
  DemoBar,
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

export default function LandingPage() {
  return (
    <>
      <DemoBar />
      <SiteHeader />
      <main>
        <Hero />
        <TechWall />
        <HowItWorks />
        <Architecture />
        <Coverage />
        <Security />
        <DemoNote />
        <Faq />
        <FinalCta />
      </main>
      <SiteFooter />
    </>
  );
}

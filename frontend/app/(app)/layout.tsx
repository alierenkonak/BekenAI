import type { Metadata } from 'next';
import { AppShell } from '@/components/app/app-shell';

export const metadata: Metadata = {
  title: 'Uygulama',
  robots: { index: false },
};

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}

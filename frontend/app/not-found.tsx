import Link from 'next/link';
import { LogoMark } from '@/components/brand';

export default function NotFound() {
  return (
    <div className="flex min-h-dvh items-center justify-center px-6">
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <LogoMark size={36} />
        <h1 className="m-0 font-serif text-5xl font-normal">Sayfa bulunamadı</h1>
        <p className="m-0 text-sm text-fg2">Aradığınız sayfa taşınmış ya da hiç var olmamış olabilir.</p>
        <div className="flex gap-2">
          <Link href="/" className="flex h-9 items-center rounded-[9px] border border-line-strong px-4 text-[13.5px] font-medium text-fg no-underline">
            Ana sayfa
          </Link>
          <Link href="/sohbet" className="flex h-9 items-center rounded-[9px] bg-inv px-4 text-[13.5px] font-medium text-inv-fg no-underline">
            Yeni sohbet
          </Link>
        </div>
      </div>
    </div>
  );
}

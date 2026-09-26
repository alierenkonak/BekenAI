import { Suspense } from 'react';
import { SourceSearch } from '@/components/app/source-search';

export default function SearchPage() {
  return (
    <Suspense fallback={null}>
      <SourceSearch />
    </Suspense>
  );
}

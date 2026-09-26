import { Suspense } from 'react';
import { NewChat } from '@/components/app/new-chat';

export default function NewChatPage() {
  return (
    <Suspense fallback={null}>
      <NewChat />
    </Suspense>
  );
}

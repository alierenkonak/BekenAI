import { notFound } from 'next/navigation';
import { ConversationView } from '@/components/app/conversation-view';

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function ConversationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!UUID_PATTERN.test(id)) notFound();
  // Keyed so switching chats never leaks state (drafts, selection) between conversations.
  return <ConversationView key={id} conversationId={id} />;
}

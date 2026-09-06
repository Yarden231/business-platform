import { redirect } from 'next/navigation';
import type { ReactNode } from 'react';

import { AppShell } from '@/components/shell/app-shell';
import { getCurrentUserFromSession } from '@/lib/api/server';

export default async function AppLayout({
  children,
}: {
  children: ReactNode;
}): Promise<React.JSX.Element> {
  const user = await getCurrentUserFromSession();
  if (user === null) {
    redirect('/login');
  }

  return <AppShell user={user}>{children}</AppShell>;
}

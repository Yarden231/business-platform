import { Suspense } from 'react';
import { redirect } from 'next/navigation';

import { PeopleList } from '@/features/people/components/people-list';
import { getCurrentUserFromSession } from '@/lib/api/server';
import { t } from '@/messages/t';

export default async function PeoplePage(): Promise<React.JSX.Element> {
  const user = await getCurrentUserFromSession();
  if (user === null) {
    redirect('/login');
  }
  if (user.must_change_password) {
    redirect('/change-password');
  }

  return (
    <Suspense fallback={<p className="text-muted-foreground">{t('common.loading')}</p>}>
      <PeopleList />
    </Suspense>
  );
}

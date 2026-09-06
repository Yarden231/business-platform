import { redirect } from 'next/navigation';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { PersonForm } from '@/features/people/components/person-form';
import { getCurrentUserFromSession } from '@/lib/api/server';
import { t } from '@/messages/t';

export default async function NewPersonPage(): Promise<React.JSX.Element> {
  const user = await getCurrentUserFromSession();
  if (user === null) {
    redirect('/login');
  }
  if (user.must_change_password) {
    redirect('/change-password');
  }

  return (
    <div className="mx-auto max-w-2xl">
      <Card>
        <CardHeader>
          <CardTitle>{t('people.form.createTitle')}</CardTitle>
        </CardHeader>
        <CardContent>
          <PersonForm mode="create" />
        </CardContent>
      </Card>
    </div>
  );
}

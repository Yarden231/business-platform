import { redirect } from 'next/navigation';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { PasswordChangeForm } from '@/features/auth/components/password-change-form';
import { getCurrentUserFromSession } from '@/lib/api/server';
import { t } from '@/messages/t';

export default async function ChangePasswordPage(): Promise<React.JSX.Element> {
  const user = await getCurrentUserFromSession();
  if (user === null) {
    redirect('/login');
  }

  const forced = user.must_change_password;

  return (
    <div className="mx-auto max-w-lg">
      <Card>
        <CardHeader>
          <CardTitle>
            {forced ? t('auth.passwordChange.forcedTitle') : t('auth.passwordChange.title')}
          </CardTitle>
          <CardDescription>
            {forced ? t('auth.passwordChange.forcedSubtitle') : t('auth.passwordChange.subtitle')}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <PasswordChangeForm forced={forced} />
        </CardContent>
      </Card>
    </div>
  );
}

import { redirect } from 'next/navigation';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { LoginForm } from '@/features/auth/components/login-form';
import { getCurrentUserFromSession } from '@/lib/api/server';
import { t } from '@/messages/t';

export default async function LoginPage(): Promise<React.JSX.Element> {
  const user = await getCurrentUserFromSession();
  if (user !== null) {
    redirect(user.must_change_password ? '/change-password' : '/');
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('auth.login.title')}</CardTitle>
        <CardDescription>{t('auth.login.subtitle')}</CardDescription>
      </CardHeader>
      <CardContent>
        <LoginForm />
      </CardContent>
    </Card>
  );
}

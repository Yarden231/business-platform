import { redirect } from 'next/navigation';

import { HomePage } from '@/components/home-page';
import { getCurrentUserFromSession } from '@/lib/api/server';

export default async function AuthenticatedHomePage(): Promise<React.JSX.Element> {
  const user = await getCurrentUserFromSession();
  if (user === null) {
    redirect('/login');
  }
  if (user.must_change_password) {
    redirect('/change-password');
  }

  return <HomePage user={user} />;
}

import { redirect } from 'next/navigation';

import { EditPersonForm } from '@/features/people/components/edit-person-form';
import { getCurrentUserFromSession } from '@/lib/api/server';

type EditPersonPageProps = {
  params: Promise<{ personId: string }>;
};

export default async function EditPersonPage({
  params,
}: EditPersonPageProps): Promise<React.JSX.Element> {
  const user = await getCurrentUserFromSession();
  if (user === null) {
    redirect('/login');
  }
  if (user.must_change_password) {
    redirect('/change-password');
  }

  const { personId } = await params;
  return <EditPersonForm personId={personId} />;
}

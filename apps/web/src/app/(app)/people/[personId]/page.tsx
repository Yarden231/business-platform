import { redirect } from 'next/navigation';

import { PersonDetailView } from '@/features/people/components/person-detail';
import { getCurrentUserFromSession } from '@/lib/api/server';

type PersonPageProps = {
  params: Promise<{ personId: string }>;
};

export default async function PersonPage({ params }: PersonPageProps): Promise<React.JSX.Element> {
  const user = await getCurrentUserFromSession();
  if (user === null) {
    redirect('/login');
  }
  if (user.must_change_password) {
    redirect('/change-password');
  }

  const { personId } = await params;
  return <PersonDetailView personId={personId} user={user} />;
}

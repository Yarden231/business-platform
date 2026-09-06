'use client';

import Link from 'next/link';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { PersonForm } from '@/features/people/components/person-form';
import { usePersonQuery } from '@/features/people/queries';
import { isPersonDetail } from '@/lib/api/types';
import { t } from '@/messages/t';

type EditPersonFormProps = {
  personId: string;
};

export function EditPersonForm({ personId }: EditPersonFormProps): React.JSX.Element {
  const personQuery = usePersonQuery(personId);
  const person = personQuery.data;

  if (personQuery.isError) {
    return <p className="text-destructive">{t('errors.codes.PERSON_NOT_FOUND')}</p>;
  }
  if (person === undefined) {
    return <p className="text-muted-foreground">{t('common.loading')}</p>;
  }
  if (!isPersonDetail(person)) {
    return (
      <div className="space-y-4">
        <p>{t('people.summaryNotice')}</p>
        <Link href={`/people/${personId}`} className="underline-offset-4 hover:underline">
          {t('people.detail.backToList')}
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <Card>
        <CardHeader>
          <CardTitle>{t('people.form.editTitle')}</CardTitle>
        </CardHeader>
        <CardContent>
          <PersonForm mode="edit" person={person} />
        </CardContent>
      </Card>
    </div>
  );
}

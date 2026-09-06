'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  useArchivePersonMutation,
  usePersonCasesQuery,
  usePersonQuery,
  useUnarchivePersonMutation,
} from '@/features/people/queries';
import type { CurrentUser, PersonDetail, PersonRead } from '@/lib/api/types';
import { isPersonDetail } from '@/lib/api/types';
import { formatInstant } from '@/lib/format';
import { messageForError, requestIdLine } from '@/messages/errors';
import { t, tDynamic } from '@/messages/t';

type PersonDetailPageProps = {
  personId: string;
  user: CurrentUser;
};

function displayName(person: PersonRead): string {
  return t('people.detail.title', { first: person.first_name, last: person.last_name });
}

function valueOrMissing(value: string | null | undefined): string {
  return value === null || value === undefined || value === '' ? t('people.detail.missing') : value;
}

export function PersonDetailView({ personId, user }: PersonDetailPageProps): React.JSX.Element {
  const router = useRouter();
  const personQuery = usePersonQuery(personId);
  const casesQuery = usePersonCasesQuery(personId);
  const archiveMutation = useArchivePersonMutation(personId);
  const unarchiveMutation = useUnarchivePersonMutation(personId);
  const isAdmin = user.role === 'ADMIN';

  if (personQuery.isError) {
    return <p className="text-destructive">{messageForError(personQuery.error)}</p>;
  }
  if (personQuery.data === undefined) {
    return <p className="text-muted-foreground">{t('common.loading')}</p>;
  }
  const person = personQuery.data;

  const canEdit = isPersonDetail(person);
  const mutationError = archiveMutation.error ?? unarchiveMutation.error;

  async function onArchive(): Promise<void> {
    if (!window.confirm(t('people.detail.archiveConfirm', { name: displayName(person) }))) {
      return;
    }
    try {
      await archiveMutation.mutateAsync();
      router.refresh();
    } catch {
      // Surface stays on the mutation error.
    }
  }

  async function onUnarchive(): Promise<void> {
    if (!window.confirm(t('people.detail.unarchiveConfirm', { name: displayName(person) }))) {
      return;
    }
    try {
      await unarchiveMutation.mutateAsync();
      router.refresh();
    } catch {
      // Surface stays on the mutation error.
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href="/people" className="text-sm underline-offset-4 hover:underline">
          {t('people.detail.backToList')}
        </Link>
      </div>

      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <h1 className="text-3xl font-bold tracking-tight">{displayName(person)}</h1>
          {person.archived_at ? (
            <Badge variant="secondary">{t('people.archivedBadge')}</Badge>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {canEdit ? (
            <Button asChild>
              <Link href={`/people/${person.id}/edit`}>{t('people.detail.edit')}</Link>
            </Button>
          ) : null}
          {isAdmin && person.archived_at === null ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                void onArchive();
              }}
              disabled={archiveMutation.isPending}
            >
              {t('people.detail.archive')}
            </Button>
          ) : null}
          {isAdmin && person.archived_at !== null ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                void onUnarchive();
              }}
              disabled={unarchiveMutation.isPending}
            >
              {t('people.detail.unarchive')}
            </Button>
          ) : null}
        </div>
      </header>

      {mutationError ? (
        <Alert variant="destructive">
          <AlertTitle>{t('people.form.errorTitle')}</AlertTitle>
          <AlertDescription>
            <p>{messageForError(mutationError)}</p>
            {requestIdLine(mutationError) ? (
              <p className="mt-1 font-mono text-xs">{requestIdLine(mutationError)}</p>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}

      {!canEdit ? (
        <Alert variant="default">
          <AlertTitle>{t('people.identifierMasked')}</AlertTitle>
          <AlertDescription>{t('people.summaryNotice')}</AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>{t('people.detail.identitySection')}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Fact
            label={t('people.detail.organization')}
            value={valueOrMissing(person.organization_name)}
          />
          {isPersonDetail(person) ? (
            <>
              <Fact
                label={t('people.detail.idType')}
                value={
                  person.id_type === null
                    ? t('people.identifierTypes.none')
                    : tDynamic(`people.identifierTypes.${person.id_type}`, person.id_type)
                }
              />
              <Fact
                label={t('people.detail.idNumber')}
                value={valueOrMissing(person.id_number)}
                ltr
              />
            </>
          ) : (
            <Fact
              label={t('people.columns.identifier')}
              value={person.id_number_masked ?? t('people.noIdentifier')}
              ltr
            />
          )}
        </CardContent>
      </Card>

      {isPersonDetail(person) ? <DetailSections person={person} /> : null}

      <Card>
        <CardHeader>
          <CardTitle>{t('people.detail.casesSection')}</CardTitle>
        </CardHeader>
        <CardContent>
          {casesQuery.data !== undefined && casesQuery.data.total === 0 ? (
            <p className="text-muted-foreground">{t('people.detail.casesEmpty')}</p>
          ) : (
            <p className="text-muted-foreground">{t('common.loading')}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function DetailSections({ person }: { person: PersonDetail }): React.JSX.Element {
  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t('people.detail.contactSection')}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Fact label={t('people.detail.email')} value={valueOrMissing(person.email)} ltr />
          <Fact label={t('people.detail.phone')} value={valueOrMissing(person.phone)} ltr />
          <Fact label={t('people.detail.address')} value={valueOrMissing(person.address)} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t('people.detail.organizationSection')}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Fact label={t('people.detail.workplace')} value={valueOrMissing(person.workplace)} />
          <Fact
            label={t('people.detail.license')}
            value={valueOrMissing(person.license_number)}
            ltr
          />
          <Fact label={t('people.detail.createdAt')} value={formatInstant(person.created_at)} />
          <Fact label={t('people.detail.updatedAt')} value={formatInstant(person.updated_at)} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t('people.detail.notesSection')}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="whitespace-pre-wrap">{valueOrMissing(person.notes)}</p>
        </CardContent>
      </Card>
    </>
  );
}

function Fact({
  label,
  value,
  ltr = false,
}: {
  label: string;
  value: string;
  ltr?: boolean;
}): React.JSX.Element {
  return (
    <div className="space-y-1">
      <p className="text-muted-foreground text-sm">{label}</p>
      <p dir={ltr ? 'ltr' : undefined} className="font-medium">
        {value}
      </p>
    </div>
  );
}

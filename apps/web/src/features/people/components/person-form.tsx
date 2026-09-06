'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';

import { FormFieldError } from '@/components/form-field-error';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  blankToNull,
  emptyPersonForm,
  personFormSchema,
  type PersonFormValues,
} from '@/features/people/schemas';
import { useCreatePersonMutation, useUpdatePersonMutation } from '@/features/people/queries';
import type {
  PersonCreateBody,
  PersonDetail,
  PersonIdType,
  PersonUpdateBody,
} from '@/lib/api/types';
import { messageForError, requestIdLine } from '@/messages/errors';
import { t } from '@/messages/t';

type PersonFormProps = {
  mode: 'create' | 'edit';
  person?: PersonDetail;
};

function valuesFromPerson(person: PersonDetail): PersonFormValues {
  return {
    first_name: person.first_name,
    last_name: person.last_name,
    id_type: person.id_type ?? '',
    id_number: person.id_number ?? '',
    email: person.email ?? '',
    phone: person.phone ?? '',
    address: person.address ?? '',
    workplace: person.workplace ?? '',
    organization_name: person.organization_name ?? '',
    license_number: person.license_number ?? '',
    notes: person.notes ?? '',
  };
}

function toCreateBody(values: PersonFormValues): PersonCreateBody {
  const idType = values.id_type === '' ? null : (values.id_type as PersonIdType);
  return {
    first_name: values.first_name,
    last_name: values.last_name,
    id_type: idType,
    id_number: blankToNull(values.id_number),
    email: blankToNull(values.email),
    phone: blankToNull(values.phone),
    address: blankToNull(values.address),
    workplace: blankToNull(values.workplace),
    organization_name: blankToNull(values.organization_name),
    license_number: blankToNull(values.license_number),
    notes: blankToNull(values.notes),
  };
}

function toUpdateBody(values: PersonFormValues): PersonUpdateBody {
  return toCreateBody(values);
}

export function PersonForm({ mode, person }: PersonFormProps): React.JSX.Element {
  const router = useRouter();
  const createMutation = useCreatePersonMutation();
  const updateMutation = useUpdatePersonMutation(person?.id ?? '');
  const mutation = mode === 'create' ? createMutation : updateMutation;
  const form = useForm<PersonFormValues>({
    resolver: zodResolver(personFormSchema),
    defaultValues: person === undefined ? emptyPersonForm : valuesFromPerson(person),
  });

  const submitError = mutation.isError ? mutation.error : null;
  const formErrorMessage = submitError ? messageForError(submitError) : null;
  const formErrorRequestId = submitError ? requestIdLine(submitError) : null;

  async function onSubmit(values: PersonFormValues): Promise<void> {
    try {
      if (mode === 'create') {
        const created = await createMutation.mutateAsync(toCreateBody(values));
        router.replace(`/people/${created.id}`);
        router.refresh();
        return;
      }
      if (person === undefined) {
        return;
      }
      await updateMutation.mutateAsync(toUpdateBody(values));
      router.replace(`/people/${person.id}`);
      router.refresh();
    } catch {
      // Surface stays on the mutation error.
    }
  }

  return (
    <form noValidate className="space-y-5" onSubmit={form.handleSubmit(onSubmit)}>
      {formErrorMessage ? (
        <Alert variant="destructive">
          <AlertTitle>{t('people.form.errorTitle')}</AlertTitle>
          <AlertDescription>
            <p>{formErrorMessage}</p>
            {formErrorRequestId ? (
              <p className="mt-1 font-mono text-xs">{formErrorRequestId}</p>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          id="first_name"
          label={t('people.form.firstName')}
          error={form.formState.errors.first_name?.message}
        >
          <Input
            id="first_name"
            autoComplete="given-name"
            aria-invalid={form.formState.errors.first_name ? true : undefined}
            aria-describedby={form.formState.errors.first_name ? 'first_name-error' : undefined}
            {...form.register('first_name')}
          />
        </Field>
        <Field
          id="last_name"
          label={t('people.form.lastName')}
          error={form.formState.errors.last_name?.message}
        >
          <Input
            id="last_name"
            autoComplete="family-name"
            aria-invalid={form.formState.errors.last_name ? true : undefined}
            aria-describedby={form.formState.errors.last_name ? 'last_name-error' : undefined}
            {...form.register('last_name')}
          />
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          id="id_type"
          label={t('people.form.idType')}
          error={form.formState.errors.id_type?.message}
        >
          <select
            id="id_type"
            className="border-input h-9 w-full rounded-md border bg-transparent px-3 text-sm shadow-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
            aria-invalid={form.formState.errors.id_type ? true : undefined}
            aria-describedby={form.formState.errors.id_type ? 'id_type-error' : undefined}
            {...form.register('id_type')}
          >
            <option value="">{t('people.form.idTypeNone')}</option>
            <option value="ISRAELI_ID">{t('people.identifierTypes.ISRAELI_ID')}</option>
            <option value="PASSPORT">{t('people.identifierTypes.PASSPORT')}</option>
            <option value="FOREIGN_ID">{t('people.identifierTypes.FOREIGN_ID')}</option>
          </select>
        </Field>
        <Field
          id="id_number"
          label={t('people.form.idNumber')}
          error={form.formState.errors.id_number?.message}
        >
          <Input
            id="id_number"
            dir="ltr"
            autoComplete="off"
            aria-invalid={form.formState.errors.id_number ? true : undefined}
            aria-describedby={form.formState.errors.id_number ? 'id_number-error' : undefined}
            {...form.register('id_number')}
          />
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          id="email"
          label={t('people.form.email')}
          error={form.formState.errors.email?.message}
        >
          <Input
            id="email"
            type="email"
            dir="ltr"
            autoComplete="email"
            aria-invalid={form.formState.errors.email ? true : undefined}
            aria-describedby={form.formState.errors.email ? 'email-error' : undefined}
            {...form.register('email')}
          />
        </Field>
        <Field
          id="phone"
          label={t('people.form.phone')}
          error={form.formState.errors.phone?.message}
        >
          <Input id="phone" dir="ltr" autoComplete="tel" {...form.register('phone')} />
        </Field>
      </div>

      <Field
        id="address"
        label={t('people.form.address')}
        error={form.formState.errors.address?.message}
      >
        <Input id="address" autoComplete="street-address" {...form.register('address')} />
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          id="organization_name"
          label={t('people.form.organization')}
          error={form.formState.errors.organization_name?.message}
        >
          <Input id="organization_name" {...form.register('organization_name')} />
        </Field>
        <Field
          id="workplace"
          label={t('people.form.workplace')}
          error={form.formState.errors.workplace?.message}
        >
          <Input id="workplace" {...form.register('workplace')} />
        </Field>
      </div>

      <Field
        id="license_number"
        label={t('people.form.license')}
        error={form.formState.errors.license_number?.message}
      >
        <Input id="license_number" dir="ltr" {...form.register('license_number')} />
      </Field>

      <Field id="notes" label={t('people.form.notes')} error={form.formState.errors.notes?.message}>
        <Textarea id="notes" rows={4} {...form.register('notes')} />
      </Field>

      <div className="flex flex-wrap gap-3">
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending
            ? t('people.form.submitting')
            : mode === 'create'
              ? t('people.form.submitCreate')
              : t('people.form.submitEdit')}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() =>
            router.push(
              mode === 'edit' && person !== undefined ? `/people/${person.id}` : '/people',
            )
          }
        >
          {t('people.form.cancel')}
        </Button>
      </div>
    </form>
  );
}

function Field({
  id,
  label,
  error,
  children,
}: {
  id: string;
  label: string;
  error?: string | undefined;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      {children}
      <FormFieldError id={`${id}-error`} message={error} />
    </div>
  );
}

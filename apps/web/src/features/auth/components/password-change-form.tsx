'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';

import { FormFieldError } from '@/components/form-field-error';
import { PasswordInput } from '@/components/password-input';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { useChangePasswordMutation } from '@/features/auth/queries';
import { passwordChangeSchema, type PasswordChangeValues } from '@/features/auth/schemas';
import { MIN_PASSWORD_LENGTH } from '@/lib/constants';
import { fieldMessagesForPasswordError, requestIdLine } from '@/messages/errors';
import { t } from '@/messages/t';

type PasswordChangeFormProps = {
  forced?: boolean;
};

export function PasswordChangeForm({ forced = false }: PasswordChangeFormProps): React.JSX.Element {
  const router = useRouter();
  const changeMutation = useChangePasswordMutation();
  const form = useForm<PasswordChangeValues>({
    resolver: zodResolver(passwordChangeSchema),
    defaultValues: { currentPassword: '', newPassword: '', confirmPassword: '' },
  });

  const submitError = changeMutation.isError ? changeMutation.error : null;
  const mapped = submitError ? fieldMessagesForPasswordError(submitError) : {};
  const requestId = submitError ? requestIdLine(submitError) : null;

  async function onSubmit(values: PasswordChangeValues): Promise<void> {
    try {
      await changeMutation.mutateAsync({
        current_password: values.currentPassword,
        new_password: values.newPassword,
      });
      router.replace('/');
      router.refresh();
    } catch {
      // Stay on the form; mapped field errors render below.
    }
  }

  return (
    <form noValidate className="space-y-5" onSubmit={form.handleSubmit(onSubmit)}>
      {mapped.form ? (
        <Alert variant="destructive">
          <AlertTitle>{t('auth.passwordChange.errorTitle')}</AlertTitle>
          <AlertDescription>
            <p>{mapped.form}</p>
            {requestId ? <p className="mt-1 font-mono text-xs">{requestId}</p> : null}
          </AlertDescription>
        </Alert>
      ) : null}

      <ul className="text-muted-foreground list-disc space-y-1 ps-5 text-sm">
        <li>{t('auth.passwordChange.requirementLength', { min: MIN_PASSWORD_LENGTH })}</li>
        <li>{t('auth.passwordChange.requirementDistinct')}</li>
        <li>{t('auth.passwordChange.requirementNotCommon')}</li>
      </ul>

      <div className="space-y-2">
        <Label htmlFor="current-password">{t('auth.passwordChange.currentPasswordLabel')}</Label>
        <PasswordInput
          id="current-password"
          autoComplete="current-password"
          aria-invalid={
            form.formState.errors.currentPassword || mapped.currentPassword ? true : undefined
          }
          aria-describedby={
            form.formState.errors.currentPassword || mapped.currentPassword
              ? 'current-password-error'
              : undefined
          }
          {...form.register('currentPassword')}
        />
        <FormFieldError
          id="current-password-error"
          message={form.formState.errors.currentPassword?.message ?? mapped.currentPassword}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="new-password">{t('auth.passwordChange.newPasswordLabel')}</Label>
        <PasswordInput
          id="new-password"
          autoComplete="new-password"
          aria-invalid={form.formState.errors.newPassword || mapped.newPassword ? true : undefined}
          aria-describedby={
            form.formState.errors.newPassword || mapped.newPassword
              ? 'new-password-error'
              : undefined
          }
          {...form.register('newPassword')}
        />
        <FormFieldError
          id="new-password-error"
          message={form.formState.errors.newPassword?.message ?? mapped.newPassword}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="confirm-password">{t('auth.passwordChange.confirmPasswordLabel')}</Label>
        <PasswordInput
          id="confirm-password"
          autoComplete="new-password"
          aria-invalid={form.formState.errors.confirmPassword ? true : undefined}
          aria-describedby={
            form.formState.errors.confirmPassword ? 'confirm-password-error' : undefined
          }
          {...form.register('confirmPassword')}
        />
        <FormFieldError
          id="confirm-password-error"
          message={form.formState.errors.confirmPassword?.message}
        />
      </div>

      <Button type="submit" className="w-full" disabled={changeMutation.isPending}>
        {changeMutation.isPending
          ? t('auth.passwordChange.submitting')
          : t('auth.passwordChange.submit')}
      </Button>

      {forced ? null : (
        <p className="text-muted-foreground text-sm leading-relaxed">
          {t('auth.passwordChange.subtitle')}
        </p>
      )}
    </form>
  );
}

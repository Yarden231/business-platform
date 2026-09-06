'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';

import { FormFieldError } from '@/components/form-field-error';
import { PasswordInput } from '@/components/password-input';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useLoginMutation } from '@/features/auth/queries';
import { loginSchema, type LoginValues } from '@/features/auth/schemas';
import { getCurrentUser } from '@/lib/api/client';
import { messageForError, requestIdLine } from '@/messages/errors';
import { t } from '@/messages/t';

export function LoginForm(): React.JSX.Element {
  const router = useRouter();
  const loginMutation = useLoginMutation();
  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  });

  const submitError = loginMutation.isError ? loginMutation.error : null;
  const formErrorMessage = submitError ? messageForError(submitError) : null;
  const formErrorRequestId = submitError ? requestIdLine(submitError) : null;

  async function onSubmit(values: LoginValues): Promise<void> {
    try {
      await loginMutation.mutateAsync({ email: values.email, password: values.password });
      const user = await getCurrentUser();
      router.replace(user.must_change_password ? '/change-password' : '/');
      router.refresh();
    } catch {
      // Surface stays on the mutation error; the form does not navigate.
    }
  }

  return (
    <form noValidate className="space-y-5" onSubmit={form.handleSubmit(onSubmit)}>
      {formErrorMessage ? (
        <Alert variant="destructive">
          <AlertTitle>{t('auth.login.errorTitle')}</AlertTitle>
          <AlertDescription>
            <p>{formErrorMessage}</p>
            {formErrorRequestId ? (
              <p className="mt-1 font-mono text-xs">{formErrorRequestId}</p>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="space-y-2">
        <Label htmlFor="email">{t('auth.login.emailLabel')}</Label>
        <Input
          id="email"
          type="email"
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          aria-invalid={form.formState.errors.email ? true : undefined}
          aria-describedby={form.formState.errors.email ? 'email-error' : undefined}
          {...form.register('email')}
        />
        <FormFieldError id="email-error" message={form.formState.errors.email?.message} />
      </div>

      <div className="space-y-2">
        <Label htmlFor="password">{t('auth.login.passwordLabel')}</Label>
        <PasswordInput
          id="password"
          autoComplete="current-password"
          aria-invalid={form.formState.errors.password ? true : undefined}
          aria-describedby={form.formState.errors.password ? 'password-error' : undefined}
          {...form.register('password')}
        />
        <FormFieldError id="password-error" message={form.formState.errors.password?.message} />
      </div>

      <Button type="submit" className="w-full" disabled={loginMutation.isPending}>
        {loginMutation.isPending ? t('auth.login.submitting') : t('auth.login.submit')}
      </Button>

      <p className="text-muted-foreground text-sm leading-relaxed">
        {t('auth.login.noSelfServiceReset')}
      </p>
    </form>
  );
}

'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useLogoutMutation } from '@/features/auth/queries';
import type { CurrentUser } from '@/lib/api/types';
import { messageForError, requestIdLine } from '@/messages/errors';
import { t, tDynamic } from '@/messages/t';

type UserMenuProps = {
  user: CurrentUser;
};

export function UserMenu({ user }: UserMenuProps): React.JSX.Element {
  const router = useRouter();
  const logoutMutation = useLogoutMutation();
  const [open, setOpen] = useState(false);

  const roleLabel = tDynamic(`shell.roles.${user.role}`, user.role);
  const logoutError = logoutMutation.isError ? logoutMutation.error : null;

  async function onLogout(): Promise<void> {
    try {
      await logoutMutation.mutateAsync();
      setOpen(false);
      router.replace('/login');
      router.refresh();
    } catch {
      // Error stays in the menu so the user can retry.
    }
  }

  return (
    <div className="flex flex-col items-stretch gap-2">
      <DropdownMenu open={open} onOpenChange={setOpen}>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" aria-label={t('shell.userMenuLabel')}>
            <span className="max-w-48 truncate">{user.full_name}</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="min-w-56">
          <DropdownMenuLabel>
            <div className="flex flex-col gap-0.5">
              <span>{user.full_name}</span>
              <span className="text-muted-foreground text-xs font-normal">{roleLabel}</span>
            </div>
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onSelect={() => {
              router.push('/change-password');
            }}
          >
            {t('shell.changePassword')}
          </DropdownMenuItem>
          <DropdownMenuItem
            disabled={logoutMutation.isPending}
            onSelect={(event) => {
              event.preventDefault();
              void onLogout();
            }}
          >
            {logoutMutation.isPending ? t('auth.logout.submitting') : t('auth.logout.action')}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {logoutError ? (
        <Alert variant="destructive">
          <AlertTitle>{t('auth.logout.errorTitle')}</AlertTitle>
          <AlertDescription>
            <p>{messageForError(logoutError)}</p>
            {requestIdLine(logoutError) ? (
              <p className="mt-1 font-mono text-xs">{requestIdLine(logoutError)}</p>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  changePassword,
  getCurrentUser,
  isPasswordChangeRequired,
  isUnauthenticated,
  login,
  logout,
} from '@/lib/api/client';
import { queryKeys } from '@/lib/api/query-keys';
import type { CurrentUser, LoginBody, PasswordChangeBody } from '@/lib/api/types';

export function useCurrentUserQuery(initialUser: CurrentUser | null) {
  return useQuery({
    queryKey: queryKeys.auth.me,
    queryFn: ({ signal }) => getCurrentUser(signal),
    initialData: initialUser ?? undefined,
    enabled: initialUser !== null,
    retry: false,
  });
}

export function useLoginMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LoginBody) => login(body),
    onSuccess: async () => {
      const user = await getCurrentUser();
      queryClient.setQueryData(queryKeys.auth.me, user);
      return user;
    },
  });
}

export function useLogoutMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => logout(),
    onSettled: async () => {
      queryClient.removeQueries({ queryKey: queryKeys.auth.me });
      await queryClient.invalidateQueries({ queryKey: queryKeys.auth.me });
    },
  });
}

export function useChangePasswordMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PasswordChangeBody) => changePassword(body),
    onSuccess: async () => {
      const user = await getCurrentUser();
      queryClient.setQueryData(queryKeys.auth.me, user);
    },
  });
}

export { isPasswordChangeRequired, isUnauthenticated };

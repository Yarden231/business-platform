import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  archivePerson,
  createPerson,
  getPerson,
  listPeople,
  listPersonCases,
  unarchivePerson,
  updatePerson,
} from '@/lib/api/client';
import { queryKeys } from '@/lib/api/query-keys';
import type { PersonCreateBody, PersonUpdateBody } from '@/lib/api/types';

export function usePeopleListQuery(params: { query: string; page: number; archived: boolean }) {
  return useQuery({
    queryKey: queryKeys.people.list(params),
    queryFn: ({ signal }) => {
      const filters: Parameters<typeof listPeople>[0] = { page: params.page };
      if (params.query) {
        filters.query = params.query;
      }
      if (params.archived) {
        filters.archived = true;
      }
      return listPeople(filters, signal);
    },
  });
}

export function usePersonQuery(personId: string) {
  return useQuery({
    queryKey: queryKeys.people.detail(personId),
    queryFn: ({ signal }) => getPerson(personId, signal),
  });
}

export function usePersonCasesQuery(personId: string) {
  return useQuery({
    queryKey: queryKeys.people.cases(personId),
    queryFn: ({ signal }) => listPersonCases(personId, signal),
  });
}

export function useCreatePersonMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PersonCreateBody) => createPerson(body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['people'] });
    },
  });
}

export function useUpdatePersonMutation(personId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PersonUpdateBody) => updatePerson(personId, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['people'] });
    },
  });
}

export function useArchivePersonMutation(personId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => archivePerson(personId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['people'] });
    },
  });
}

export function useUnarchivePersonMutation(personId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unarchivePerson(personId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['people'] });
    },
  });
}

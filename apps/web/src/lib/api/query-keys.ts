/** Query-key factory. One place so invalidation cannot misspell a key. */
export const queryKeys = {
  auth: {
    me: ['auth', 'me'] as const,
  },
  health: ['health'] as const,
  people: {
    list: (params: { query: string; page: number; archived: boolean }) =>
      ['people', 'list', params] as const,
    detail: (personId: string) => ['people', 'detail', personId] as const,
    cases: (personId: string) => ['people', 'cases', personId] as const,
  },
};

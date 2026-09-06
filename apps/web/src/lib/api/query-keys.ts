/** Query-key factory. One place so invalidation cannot misspell a key. */
export const queryKeys = {
  auth: {
    me: ['auth', 'me'] as const,
  },
  health: ['health'] as const,
};

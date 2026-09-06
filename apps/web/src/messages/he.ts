/**
 * Hebrew message catalog.
 *
 * Every user-visible string in the application lives here, never inline in
 * JSX (ADR-0018). Phase 3 introduces the `t()` accessor, the error-code to
 * Hebrew mapper and the rest of the catalog; Phase 0 only needs the strings
 * its single screen renders.
 */
export const he = {
  app: {
    documentTitle: 'כהן איזונים פיננסיים — מערכת ניהול תיקים',
    documentDescription: 'מערכת פנימית לניהול תיקים של כהן איזונים פיננסיים',
    organizationName: 'כהן איזונים פיננסיים',
    productName: 'מערכת ניהול תיקים',
    environmentBadge: 'סביבת פיתוח',
    environmentDescription:
      'סביבת הפיתוח פועלת. מסך זה נועד לאימות התשתית בלבד — עדיין אין בו יכולות מוצר.',
  },
  apiHealth: {
    title: 'חיבור לשרת',
    checking: 'בודק…',
    online: 'מחובר',
    offline: 'אין חיבור',
  },
} as const;

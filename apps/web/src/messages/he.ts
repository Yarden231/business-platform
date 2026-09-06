/**
 * Hebrew message catalog.
 *
 * Every user-visible string in the application lives here, never inline in JSX
 * (ADR-0018). Read it through `t()` from `@/messages/t`, which resolves a
 * dotted path and interpolates `{placeholders}`.
 *
 * This is the only file in `src/` permitted to contain Hebrew characters, and
 * `tests/hebrew-copy.test.ts` fails the build if any other one does.
 *
 * `errors.codes` must cover every member of the API's `ErrorCode` enum. It is
 * typed as `Record<ErrorCode, string>` against the generated OpenAPI types
 * (ADR-0039), so a code added to the API without Hebrew copy is a compile
 * error rather than an English string leaking into the UI.
 */
import type { ErrorCode, PasswordIssue } from '@/lib/api/types';

const errorCodeMessages: Record<ErrorCode, string> = {
  // Infrastructure
  BAD_REQUEST: 'הבקשה שנשלחה אינה תקינה.',
  VALIDATION_ERROR: 'חלק מהפרטים שהוזנו אינם תקינים.',
  NOT_FOUND: 'הפריט המבוקש לא נמצא.',
  METHOD_NOT_ALLOWED: 'הפעולה אינה נתמכת בכתובת הזו.',
  CONFLICT: 'הפעולה מתנגשת עם המצב הנוכחי של הפריט. רעננו את הדף ונסו שוב.',
  TOO_MANY_REQUESTS: 'בוצעו יותר מדי ניסיונות. המתינו כמה דקות ונסו שוב.',
  INTERNAL_ERROR: 'אירעה שגיאה בשרת. נסו שוב, ואם התקלה חוזרת פנו לתמיכה עם מספר הבקשה.',
  SERVICE_UNAVAILABLE: 'השירות אינו זמין כרגע. נסו שוב בעוד רגע.',

  // Authentication and sessions
  AUTH_REQUIRED: 'יש להתחבר כדי להמשיך.',
  // Deliberately does not say which of the two was wrong: the API answers every
  // login failure identically so it cannot be used to discover which accounts
  // exist (docs/security.md §2), and Hebrew copy that guessed would undo that.
  AUTH_INVALID_CREDENTIALS: 'כתובת הדוא״ל או הסיסמה אינן נכונות.',
  AUTH_SESSION_EXPIRED: 'תוקף ההתחברות פג. יש להתחבר מחדש.',
  AUTH_ACCOUNT_INACTIVE: 'החשבון הזה אינו פעיל. פנו למנהל המערכת.',
  CSRF_TOKEN_INVALID: 'פג תוקף אישור האבטחה של הטופס. רעננו את הדף ונסו שוב.',

  // Passwords
  PASSWORD_CHANGE_REQUIRED: 'יש להחליף את הסיסמה הזמנית לפני המשך העבודה במערכת.',
  PASSWORD_INVALID: 'הסיסמה החדשה אינה עומדת בדרישות.',
  CURRENT_PASSWORD_INVALID: 'הסיסמה הנוכחית שהוזנה אינה נכונה.',

  // Authorization and user administration
  FORBIDDEN: 'אין לך הרשאה לבצע את הפעולה הזו.',
  USER_NOT_FOUND: 'המשתמש המבוקש לא נמצא.',
  USER_EMAIL_CONFLICT: 'כתובת הדוא״ל הזו משויכת כבר לחשבון אחר.',
  USER_SELF_DEACTIVATION: 'לא ניתן להשבית את החשבון שממנו אתם מחוברים.',
  USER_LAST_ADMIN: 'לא ניתן להשבית או להוריד בתפקיד את מנהל המערכת האחרון.',

  // People
  PERSON_NOT_FOUND: 'האדם המבוקש לא נמצא.',
  PERSON_ACCESS_DENIED:
    'אין לך הרשאה לערוך את האדם הזה. ההרשאה ניתנת כשהוא משתתף בתיק שמשויך אליך.',
  PERSON_IDENTIFIER_CONFLICT: 'מזהה זה כבר משויך לאדם אחר במערכת.',
  PERSON_ALREADY_ARCHIVED: 'הרשומה הזו כבר בארכיון.',
  PERSON_NOT_ARCHIVED: 'הרשומה הזו אינה בארכיון.',
};

/** One entry per `details[].issue` the API returns with `PASSWORD_INVALID`. */
const passwordIssueMessages: Record<PasswordIssue, string> = {
  too_short: 'הסיסמה חייבת להכיל {min} תווים לפחות.',
  too_long: 'הסיסמה חייבת להכיל עד {max} תווים.',
  common: 'הסיסמה שנבחרה מנוחשת בקלות. בחרו סיסמה אחרת.',
  whitespace_only: 'הסיסמה אינה יכולה להיות רווחים בלבד.',
  same_as_current: 'הסיסמה החדשה חייבת להיות שונה מהסיסמה הנוכחית.',
};

export const he = {
  app: {
    documentTitle: 'כהן איזונים פיננסיים — מערכת ניהול תיקים',
    documentDescription: 'מערכת פנימית לניהול תיקים של כהן איזונים פיננסיים',
    organizationName: 'כהן איזונים פיננסיים',
    productName: 'מערכת ניהול תיקים',
    skipToContent: 'דלגו לתוכן הראשי',
  },
  common: {
    loading: 'טוען…',
    show: 'הצגה',
    hide: 'הסתרה',
  },
  auth: {
    login: {
      title: 'התחברות למערכת',
      subtitle: 'הזינו את כתובת הדוא״ל והסיסמה שקיבלתם ממנהל המערכת.',
      emailLabel: 'כתובת דוא״ל',
      passwordLabel: 'סיסמה',
      submit: 'התחברות',
      submitting: 'מתחבר…',
      errorTitle: 'ההתחברות נכשלה',
      // There is no self-service password reset in Release 1 (ADR-0026), so the
      // screen says who to ask instead of offering a link that cannot exist.
      noSelfServiceReset: 'שכחתם את הסיסמה? פנו למנהל המערכת לקבלת סיסמה זמנית חדשה.',
    },
    logout: {
      action: 'התנתקות',
      submitting: 'מתנתק…',
      errorTitle: 'ההתנתקות נכשלה',
    },
    passwordChange: {
      title: 'החלפת סיסמה',
      forcedTitle: 'החלפת הסיסמה הזמנית',
      subtitle: 'לאחר החלפת הסיסמה תתבצע התנתקות מכל המכשירים האחרים.',
      forcedSubtitle:
        'הסיסמה שקיבלתם היא זמנית. בחרו סיסמה קבועה כדי להמשיך לעבוד במערכת. שאר המערכת חסומה עד להחלפה.',
      currentPasswordLabel: 'הסיסמה הנוכחית',
      newPasswordLabel: 'סיסמה חדשה',
      confirmPasswordLabel: 'אימות הסיסמה החדשה',
      requirementsTitle: 'דרישות הסיסמה',
      requirementLength: 'לפחות {min} תווים.',
      requirementDistinct: 'שונה מהסיסמה הנוכחית.',
      requirementNotCommon: 'לא סיסמה מנוחשת בקלות.',
      submit: 'החלפת הסיסמה',
      submitting: 'מחליף…',
      errorTitle: 'החלפת הסיסמה נכשלה',
    },
    validation: {
      emailRequired: 'יש להזין כתובת דוא״ל.',
      emailTooLong: 'כתובת הדוא״ל ארוכה מדי.',
      passwordRequired: 'יש להזין סיסמה.',
      newPasswordTooShort: 'הסיסמה החדשה חייבת להכיל {min} תווים לפחות.',
      newPasswordTooLong: 'הסיסמה החדשה חייבת להכיל עד {max} תווים.',
      confirmMismatch: 'שתי הסיסמאות אינן זהות.',
      newPasswordSameAsCurrent: 'הסיסמה החדשה חייבת להיות שונה מהסיסמה הנוכחית.',
    },
  },
  shell: {
    navigationLabel: 'ניווט ראשי',
    mainLabel: 'תוכן ראשי',
    userMenuLabel: 'תפריט המשתמש',
    changePassword: 'החלפת סיסמה',
    roles: {
      ADMIN: 'מנהל מערכת',
      EMPLOYEE: 'עובד',
    },
    navigation: {
      home: 'דף הבית',
      people: 'אנשים',
    },
  },
  home: {
    title: 'שלום, {name}',
    subtitle: 'זהו החשבון שממנו אתם מחוברים כרגע.',
    accountSectionTitle: 'פרטי החשבון',
    emailLabel: 'כתובת דוא״ל',
    roleLabel: 'תפקיד',
    systemSectionTitle: 'מצב המערכת',
    scopeNotice:
      'בגרסה זו מיושמים ההתחברות, ספר האנשים וניהול ההרשאות. מסכי תיקים, מסמכים ולוח הבקרה נבנים בשלבים הבאים.',
  },
  people: {
    title: 'ספר אנשים',
    subtitle: 'אנשי קשר שחוזרים בין תיקים: צדדים, עורכי דין וגורמי חוץ.',
    searchLabel: 'חיפוש',
    searchPlaceholder: 'שם, מזהה או ארגון',
    searchSubmit: 'חיפוש',
    create: 'אדם חדש',
    empty: 'לא נמצאו אנשים התואמים את החיפוש.',
    emptyDefault: 'עדיין אין אנשים בספר. הוסיפו את הרשומה הראשונה.',
    showArchived: 'הצגת רשומות בארכיון',
    archivedBadge: 'בארכיון',
    pagination: {
      page: 'עמוד {page} מתוך {pages}',
      previous: 'הקודם',
      next: 'הבא',
      summary: '{total} אנשים',
    },
    columns: {
      name: 'שם',
      organization: 'ארגון',
      identifier: 'מזהה',
      status: 'סטטוס',
    },
    identifierTypes: {
      ISRAELI_ID: 'תעודת זהות',
      PASSPORT: 'דרכון',
      FOREIGN_ID: 'מזהה זר',
      none: 'ללא מזהה',
    },
    identifierMasked: 'מזהה מוסתר',
    noIdentifier: 'אין מזהה',
    noOrganization: 'אין ארגון',
    summaryNotice: 'מוצג תקציר בלבד. פרטים מלאים ועריכה זמינים כשהאדם משתתף בתיק שמשויך אליכם.',
    detail: {
      title: '{first} {last}',
      contactSection: 'פרטי קשר',
      identitySection: 'זיהוי',
      notesSection: 'הערות',
      organizationSection: 'ארגון ועיסוק',
      casesSection: 'תיקים',
      casesEmpty: 'אין תיקים. שיוך לאנשים יגיע עם מסך התיקים.',
      email: 'כתובת דוא״ל',
      phone: 'טלפון',
      address: 'כתובת',
      workplace: 'מקום עבודה',
      organization: 'ארגון',
      license: 'מספר רישיון',
      idType: 'סוג מזהה',
      idNumber: 'מספר מזהה',
      notes: 'הערות',
      createdAt: 'נוצר',
      updatedAt: 'עודכן',
      edit: 'עריכה',
      archive: 'העברה לארכיון',
      unarchive: 'שחזור מהארכיון',
      archiveConfirm: 'להעביר את {name} לארכיון? הרשומה תוסתר מהרשימה אך תישאר בתיקים קיימים.',
      unarchiveConfirm: 'לשחזר את {name} מהארכיון?',
      backToList: 'חזרה לספר האנשים',
      missing: 'אין',
    },
    form: {
      createTitle: 'אדם חדש',
      editTitle: 'עריכת אדם',
      firstName: 'שם פרטי',
      lastName: 'שם משפחה',
      idType: 'סוג מזהה',
      idTypeNone: 'ללא מזהה',
      idNumber: 'מספר מזהה',
      email: 'כתובת דוא״ל',
      phone: 'טלפון',
      address: 'כתובת',
      workplace: 'מקום עבודה',
      organization: 'ארגון',
      license: 'מספר רישיון',
      notes: 'הערות',
      submitCreate: 'יצירה',
      submitEdit: 'שמירה',
      submitting: 'שומר…',
      cancel: 'ביטול',
      errorTitle: 'לא ניתן לשמור את הרשומה',
    },
    validation: {
      firstNameRequired: 'יש להזין שם פרטי.',
      lastNameRequired: 'יש להזין שם משפחה.',
      identifierPair: 'סוג המזהה והמספר חייבים להופיע יחד, או שניהם להישאר ריקים.',
      israeliIdInvalid: 'מספר תעודת הזהות אינו תקין.',
      emailInvalid: 'כתובת הדוא״ל אינה תקינה.',
    },
  },
  apiHealth: {
    title: 'חיבור לשרת',
    checking: 'בודק…',
    online: 'מחובר',
    offline: 'אין חיבור',
  },
  errors: {
    unexpected: 'אירעה שגיאה בלתי צפויה. נסו שוב.',
    // A fetch that never reached the server: no envelope, no code, no request
    // id — so the copy must not promise one.
    network: 'אין חיבור לשרת. בדקו את החיבור לרשת ונסו שוב.',
    requestId: 'מספר בקשה: {requestId}',
    codes: errorCodeMessages,
    passwordIssues: passwordIssueMessages,
  },
} as const;

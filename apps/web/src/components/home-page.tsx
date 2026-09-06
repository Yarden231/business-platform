import { ApiHealthStatus } from '@/components/api-health-status';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { CurrentUser } from '@/lib/api/types';
import { t, tDynamic } from '@/messages/t';

type HomePageProps = {
  user: CurrentUser;
};

export function HomePage({ user }: HomePageProps): React.JSX.Element {
  const roleLabel = tDynamic(`shell.roles.${user.role}`, user.role);

  return (
    <div className="space-y-8">
      <header className="space-y-2 text-start">
        <h1 className="text-3xl font-bold tracking-tight">
          {t('home.title', { name: user.full_name })}
        </h1>
        <p className="text-muted-foreground text-lg">{t('home.subtitle')}</p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>{t('home.accountSectionTitle')}</CardTitle>
          <CardDescription>{t('home.scopeNotice')}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1">
            <p className="text-muted-foreground text-sm">{t('home.emailLabel')}</p>
            <p dir="ltr" className="font-medium">
              {user.email}
            </p>
          </div>
          <div className="space-y-1">
            <p className="text-muted-foreground text-sm">{t('home.roleLabel')}</p>
            <p className="font-medium">{roleLabel}</p>
          </div>
        </CardContent>
      </Card>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">{t('home.systemSectionTitle')}</h2>
        <ApiHealthStatus />
      </section>
    </div>
  );
}

import { ApiHealthStatus } from '@/components/api-health-status';
import { Badge } from '@/components/ui/badge';
import { he } from '@/messages/he';

export default function HomePage(): React.JSX.Element {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-2xl flex-col justify-center gap-8 px-6 py-16">
      <header className="space-y-3 text-start">
        <Badge variant="outline">{he.app.environmentBadge}</Badge>
        <h1 className="text-3xl font-bold tracking-tight text-balance sm:text-4xl">
          {he.app.organizationName}
        </h1>
        <p className="text-muted-foreground text-xl">{he.app.productName}</p>
      </header>

      <p className="text-muted-foreground max-w-prose text-start leading-relaxed">
        {he.app.environmentDescription}
      </p>

      <ApiHealthStatus />
    </main>
  );
}

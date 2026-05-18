import { useAuth } from "@/auth/AuthContext";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

export function SettingsPage() {
  const { user } = useAuth();

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-medium uppercase tracking-wide text-slate-500">Account</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-2 text-sm text-slate-500">Review the current user profile and runtime boundaries.</p>
      </div>

      <Card>
        <CardHeader className="border-b border-slate-200 pb-4">
          <h2 className="font-semibold">Profile</h2>
        </CardHeader>
        <CardContent className="grid gap-4 p-5 md:grid-cols-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Username</p>
            <p className="mt-1 font-medium">{user?.username ?? "-"}</p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Email</p>
            <p className="mt-1 font-medium">{user?.email ?? "-"}</p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">User ID</p>
            <p className="mt-1 font-medium">{user?.id ?? "-"}</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-slate-200 pb-4">
          <h2 className="font-semibold">File policy</h2>
        </CardHeader>
        <CardContent className="grid gap-4 p-5 md:grid-cols-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Allowed types</p>
            <p className="mt-1 font-medium">PDF, Markdown, TXT</p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Frontend limit</p>
            <p className="mt-1 font-medium">10 MB per file</p>
          </div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Storage names</p>
            <p className="mt-1 font-medium">UUID-based safe filenames</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

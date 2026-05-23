import { useAuth } from "@/auth/AuthContext";

function Row({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-2xl px-3 py-2.5 hover:bg-slate-50">
      <span className="text-sm text-slate-400">{label}</span>
      <span className="truncate text-sm font-medium text-slate-800">{value || "-"}</span>
    </div>
  );
}

export function SettingsPage() {
  const { user } = useAuth();

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">设置</h1>

      <section className="rounded-3xl border border-slate-100 bg-white p-3">
        <Row label="用户名" value={user?.username ?? "-"} />
        <Row label="邮箱" value={user?.email ?? "-"} />
        <Row label="ID" value={user?.id ?? "-"} />
      </section>

      <section className="rounded-3xl border border-slate-100 bg-white p-3">
        <Row label="文件" value="PDF / EPUB / Markdown / TXT / Image" />
        <Row label="上传限制" value="10 MB" />
        <Row label="存储" value="UUID" />
      </section>
    </div>
  );
}

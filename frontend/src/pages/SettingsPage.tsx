import { useEffect, useState } from "react";
import { Database, Monitor, RotateCcw, Shield, UserRound } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/button";

const STORAGE_KEY = "second-brain:user-settings";

type AppearanceMode = "system" | "light" | "dark";
type FontScale = "compact" | "default" | "comfortable";
type LandingPage = "dashboard" | "knowledge" | "notes" | "chat";

type UserSettings = {
  displayName: string;
  appearance: AppearanceMode;
  fontScale: FontScale;
  landingPage: LandingPage;
  autoOpenSearch: boolean;
  uploadAutoTag: boolean;
  showProcessingToast: boolean;
  confirmBeforeDelete: boolean;
  hideMetadata: boolean;
};

const defaultSettings: UserSettings = {
  displayName: "",
  appearance: "system",
  fontScale: "default",
  landingPage: "knowledge",
  autoOpenSearch: true,
  uploadAutoTag: true,
  showProcessingToast: true,
  confirmBeforeDelete: true,
  hideMetadata: false,
};

const appearanceLabels: Record<AppearanceMode, string> = { system: "跟随系统", light: "浅色", dark: "深色" };
const fontScaleLabels: Record<FontScale, string> = { compact: "紧凑", default: "默认", comfortable: "舒适" };
const landingPageLabels: Record<LandingPage, string> = { dashboard: "首页", knowledge: "知识库", notes: "笔记", chat: "问答" };

function loadSettings(): UserSettings {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return { ...defaultSettings, ...parsed, hideMetadata: parsed.hideMetadata ?? parsed.hideSensitiveMetadata ?? defaultSettings.hideMetadata };
  } catch {
    return defaultSettings;
  }
}

function resolveDarkMode(appearance: AppearanceMode) {
  const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  return appearance === "dark" || (appearance === "system" && prefersDark);
}

function applySettings(settings: UserSettings) {
  const isDark = resolveDarkMode(settings.appearance);
  document.documentElement.classList.toggle("dark", isDark);
  document.documentElement.dataset.theme = isDark ? "dark" : "light";
  document.documentElement.style.colorScheme = isDark ? "dark" : "light";
  document.documentElement.style.fontSize = settings.fontScale === "compact" ? "15px" : settings.fontScale === "comfortable" ? "17px" : "16px";
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

function Section({ title, icon: Icon, children }: { title: string; icon: typeof UserRound; children: React.ReactNode }) {
  return (
    <section className="rounded-3xl border border-border bg-card p-5 text-card-foreground shadow-sm shadow-slate-100/60 dark:shadow-none">
      <div className="mb-4 flex items-center gap-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-2xl bg-slate-50 text-slate-700 ring-1 ring-slate-100 dark:bg-slate-900 dark:text-slate-200 dark:ring-slate-800">
          <Icon className="h-4 w-4" />
        </span>
        <h2 className="text-base font-semibold text-slate-950 dark:text-slate-50">{title}</h2>
      </div>
      <div className="divide-y divide-border overflow-hidden rounded-2xl border border-border">{children}</div>
    </section>
  );
}

function SelectItem<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: { value: T; label: string }[]; onChange: (value: T) => void }) {
  return (
    <label className="grid gap-3 bg-card px-4 py-3 sm:grid-cols-[1fr_220px] sm:items-center">
      <span className="text-sm font-medium text-slate-800 dark:text-slate-100">{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value as T)} className="h-10 rounded-xl border border-input bg-background px-3 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring/20">
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>
  );
}

function ToggleItem({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-4 bg-card px-4 py-3">
      <span className="text-sm font-medium text-slate-800 dark:text-slate-100">{label}</span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="h-5 w-5 rounded border-slate-300 text-slate-950 focus:ring-slate-900 dark:border-slate-600 dark:bg-slate-900" />
    </label>
  );
}

export function SettingsPage() {
  const { user } = useAuth();
  const [settings, setSettings] = useState<UserSettings>(() => loadSettings());

  useEffect(() => {
    applySettings(settings);
  }, [settings]);

  useEffect(() => {
    const mediaQuery = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mediaQuery) return undefined;
    const handleChange = () => settings.appearance === "system" && applySettings(settings);
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [settings]);

  const displayName = settings.displayName.trim() || user?.username || "用户";
  const activeTheme = resolveDarkMode(settings.appearance) ? "深色" : "浅色";

  function updateSetting<K extends keyof UserSettings>(key: K, value: UserSettings[K]) {
    setSettings((current) => {
      const next = { ...current, [key]: value };
      applySettings(next);
      return next;
    });
  }

  function resetSettings() {
    window.localStorage.removeItem(STORAGE_KEY);
    setSettings(defaultSettings);
    applySettings(defaultSettings);
  }

  return (
    <div className="mx-auto max-w-5xl space-y-5 text-foreground">
      <header className="flex flex-col gap-3 rounded-3xl border border-border bg-card p-5 shadow-sm shadow-slate-100/60 dark:shadow-none sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">设置</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">修改后立即生效，并记录在本机。</p>
        </div>
        <Button type="button" variant="outline" onClick={resetSettings} className="w-fit rounded-xl border-border shadow-none">
          <RotateCcw className="h-4 w-4" />恢复默认
        </Button>
      </header>

      <div className="grid gap-5 lg:grid-cols-[1fr_280px]">
        <main className="space-y-5">
          <Section title="账户" icon={UserRound}>
            <label className="grid gap-3 bg-card px-4 py-3 sm:grid-cols-[1fr_260px] sm:items-center">
              <span className="text-sm font-medium text-slate-800 dark:text-slate-100">显示昵称</span>
              <input value={settings.displayName} onChange={(event) => updateSetting("displayName", event.target.value)} placeholder={user?.username || "输入昵称"} className="h-10 rounded-xl border border-input bg-background px-3 text-sm text-foreground outline-none placeholder:text-slate-400 focus:ring-2 focus:ring-ring/20" />
            </label>
          </Section>

          <Section title="外观" icon={Monitor}>
            <SelectItem label="外观模式" value={settings.appearance} onChange={(value) => updateSetting("appearance", value)} options={[{ value: "system", label: "跟随系统" }, { value: "light", label: "浅色" }, { value: "dark", label: "深色" }]} />
            <SelectItem label="界面字号" value={settings.fontScale} onChange={(value) => updateSetting("fontScale", value)} options={[{ value: "compact", label: "紧凑" }, { value: "default", label: "默认" }, { value: "comfortable", label: "舒适" }]} />
            <SelectItem label="默认入口" value={settings.landingPage} onChange={(value) => updateSetting("landingPage", value)} options={[{ value: "dashboard", label: "首页" }, { value: "knowledge", label: "知识库" }, { value: "notes", label: "笔记" }, { value: "chat", label: "问答" }]} />
          </Section>

          <Section title="知识库" icon={Database}>
            <ToggleItem label="进入后聚焦搜索" checked={settings.autoOpenSearch} onChange={(value) => updateSetting("autoOpenSearch", value)} />
            <ToggleItem label="自动建议标签" checked={settings.uploadAutoTag} onChange={(value) => updateSetting("uploadAutoTag", value)} />
            <ToggleItem label="处理状态提醒" checked={settings.showProcessingToast} onChange={(value) => updateSetting("showProcessingToast", value)} />
          </Section>

          <Section title="隐私" icon={Shield}>
            <ToggleItem label="删除前确认" checked={settings.confirmBeforeDelete} onChange={(value) => updateSetting("confirmBeforeDelete", value)} />
            <ToggleItem label="隐藏文件元数据" checked={settings.hideMetadata} onChange={(value) => updateSetting("hideMetadata", value)} />
          </Section>
        </main>

        <aside className="h-fit rounded-3xl border border-border bg-card p-5 text-card-foreground shadow-sm shadow-slate-100/60 dark:shadow-none">
          <div className="flex items-center gap-3">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-950 text-sm font-semibold text-white dark:bg-slate-100 dark:text-slate-950">{displayName.slice(0, 1).toUpperCase()}</span>
            <div className="min-w-0">
              <p className="truncate font-semibold text-slate-950 dark:text-slate-50">{displayName}</p>
              <p className="truncate text-sm text-slate-500 dark:text-slate-400">{user?.email ?? "未绑定邮箱"}</p>
            </div>
          </div>
          <div className="mt-5 space-y-2 text-sm">
            <div className="flex items-center justify-between rounded-2xl bg-slate-50 px-3 py-2.5 dark:bg-slate-900"><span className="text-slate-500 dark:text-slate-400">外观</span><span className="font-medium text-slate-900 dark:text-slate-100">{appearanceLabels[settings.appearance]}</span></div>
            <div className="flex items-center justify-between rounded-2xl bg-slate-50 px-3 py-2.5 dark:bg-slate-900"><span className="text-slate-500 dark:text-slate-400">当前主题</span><span className="font-medium text-slate-900 dark:text-slate-100">{activeTheme}</span></div>
            <div className="flex items-center justify-between rounded-2xl bg-slate-50 px-3 py-2.5 dark:bg-slate-900"><span className="text-slate-500 dark:text-slate-400">字号</span><span className="font-medium text-slate-900 dark:text-slate-100">{fontScaleLabels[settings.fontScale]}</span></div>
            <div className="flex items-center justify-between rounded-2xl bg-slate-50 px-3 py-2.5 dark:bg-slate-900"><span className="text-slate-500 dark:text-slate-400">入口</span><span className="font-medium text-slate-900 dark:text-slate-100">{landingPageLabels[settings.landingPage]}</span></div>
          </div>
        </aside>
      </div>
    </div>
  );
}

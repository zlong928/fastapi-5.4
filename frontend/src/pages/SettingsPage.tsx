import { useEffect, useMemo, useState } from "react";
import { Bell, Check, Database, Monitor, RotateCcw, Save, Shield, SlidersHorizontal, UserRound } from "lucide-react";
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
  weeklyDigest: boolean;
  confirmBeforeDelete: boolean;
  hideSensitiveMetadata: boolean;
  readerFullscreenHint: boolean;
};

const defaultSettings: UserSettings = {
  displayName: "",
  appearance: "system",
  fontScale: "default",
  landingPage: "knowledge",
  autoOpenSearch: true,
  uploadAutoTag: true,
  showProcessingToast: true,
  weeklyDigest: false,
  confirmBeforeDelete: true,
  hideSensitiveMetadata: false,
  readerFullscreenHint: true,
};

const appearanceLabels: Record<AppearanceMode, string> = {
  system: "跟随系统",
  light: "浅色",
  dark: "深色",
};

const fontScaleLabels: Record<FontScale, string> = {
  compact: "紧凑",
  default: "默认",
  comfortable: "舒适",
};

const landingPageLabels: Record<LandingPage, string> = {
  dashboard: "首页概览",
  knowledge: "知识库",
  notes: "笔记",
  chat: "问答",
};

function loadSettings(): UserSettings {
  if (typeof window === "undefined") return defaultSettings;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? { ...defaultSettings, ...JSON.parse(raw) } : defaultSettings;
  } catch {
    return defaultSettings;
  }
}

function applyVisualSettings(settings: UserSettings) {
  if (typeof document === "undefined") return;
  const prefersDark = typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  const shouldUseDark = settings.appearance === "dark" || (settings.appearance === "system" && prefersDark);

  document.documentElement.classList.toggle("dark", shouldUseDark);
  document.documentElement.style.colorScheme = shouldUseDark ? "dark" : "light";
  document.documentElement.style.fontSize = settings.fontScale === "compact" ? "15px" : settings.fontScale === "comfortable" ? "17px" : "16px";
}

function SettingsCard({
  icon: Icon,
  title,
  description,
  children,
}: {
  icon: typeof SlidersHorizontal;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-3xl border border-slate-100 bg-white p-5 shadow-sm shadow-slate-100/60">
      <div className="mb-4 flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-slate-50 text-slate-700 ring-1 ring-slate-100">
          <Icon className="h-5 w-5" />
        </span>
        <div>
          <h2 className="text-base font-semibold text-slate-900">{title}</h2>
          <p className="mt-1 text-sm leading-6 text-slate-500">{description}</p>
        </div>
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function FieldLabel({ label, hint }: { label: string; hint?: string }) {
  return (
    <div>
      <p className="text-sm font-medium text-slate-800">{label}</p>
      {hint ? <p className="mt-0.5 text-xs leading-5 text-slate-500">{hint}</p> : null}
    </div>
  );
}

function ToggleRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-4 rounded-2xl border border-slate-100 px-4 py-3 transition hover:bg-slate-50">
      <FieldLabel label={label} hint={hint} />
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="h-5 w-5 rounded border-slate-300 text-slate-900 focus:ring-slate-900"
      />
    </label>
  );
}

function SelectRow<T extends string>({
  label,
  hint,
  value,
  options,
  onChange,
}: {
  label: string;
  hint: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <label className="grid gap-3 rounded-2xl border border-slate-100 px-4 py-3 sm:grid-cols-[1fr_220px] sm:items-center">
      <FieldLabel label={label} hint={hint} />
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as T)}
        className="h-10 rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-800 outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
      >
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>
  );
}

function SummaryRow({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-2xl bg-slate-50 px-3 py-2.5 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className={strong ? "font-semibold text-slate-950" : "font-medium text-slate-800"}>{value}</span>
    </div>
  );
}

function onOff(value: boolean) {
  return value ? "开启" : "关闭";
}

export function SettingsPage() {
  const { user } = useAuth();
  const [savedSettings, setSavedSettings] = useState<UserSettings>(() => loadSettings());
  const [draftSettings, setDraftSettings] = useState<UserSettings>(() => loadSettings());
  const [status, setStatus] = useState("已加载本机偏好");

  useEffect(() => {
    applyVisualSettings(savedSettings);
  }, [savedSettings]);

  const isDirty = useMemo(() => JSON.stringify(savedSettings) !== JSON.stringify(draftSettings), [draftSettings, savedSettings]);
  const effectiveName = draftSettings.displayName.trim() || user?.username || "用户";

  function updateDraft<K extends keyof UserSettings>(key: K, value: UserSettings[K]) {
    setDraftSettings((current) => ({ ...current, [key]: value }));
    setStatus("有未保存的更改");
  }

  function saveSettings() {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(draftSettings));
    setSavedSettings(draftSettings);
    applyVisualSettings(draftSettings);
    setStatus("设置已保存并生效");
  }

  function resetSettings() {
    window.localStorage.removeItem(STORAGE_KEY);
    setDraftSettings(defaultSettings);
    setSavedSettings(defaultSettings);
    applyVisualSettings(defaultSettings);
    setStatus("已恢复默认设置");
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-col gap-4 rounded-3xl border border-slate-100 bg-gradient-to-br from-white to-slate-50 p-5 shadow-sm shadow-slate-100/70 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-sm font-medium text-slate-500">个人工作台偏好</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">设置</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
            调整显示、知识库默认行为、通知和隐私偏好。设置会保存到当前浏览器，并在下次打开时自动恢复。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 text-xs font-medium text-slate-600 ring-1 ring-slate-100">
            <Check className="h-3.5 w-3.5" />{status}
          </span>
          <Button type="button" variant="outline" onClick={resetSettings} className="rounded-xl border-slate-200 shadow-none">
            <RotateCcw className="h-4 w-4" />恢复默认
          </Button>
          <Button type="button" onClick={saveSettings} disabled={!isDirty} className="rounded-xl bg-slate-950 text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50">
            <Save className="h-4 w-4" />保存设置
          </Button>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
        <div className="space-y-5">
          <SettingsCard icon={UserRound} title="账户展示" description="这些设置影响你在本机界面中看到的昵称和身份信息，不会修改登录凭据。">
            <label className="grid gap-3 rounded-2xl border border-slate-100 px-4 py-3 sm:grid-cols-[1fr_260px] sm:items-center">
              <FieldLabel label="显示昵称" hint="为空时默认使用账户用户名。" />
              <input
                value={draftSettings.displayName}
                onChange={(event) => updateDraft("displayName", event.target.value)}
                placeholder={user?.username || "输入昵称"}
                className="h-10 rounded-xl border border-slate-200 px-3 text-sm outline-none transition placeholder:text-slate-400 focus:border-slate-400 focus:ring-2 focus:ring-slate-100"
              />
            </label>
            <div className="grid gap-3 rounded-2xl bg-slate-50 p-4 text-sm text-slate-600 sm:grid-cols-3">
              <div><span className="block text-xs text-slate-400">用户名</span>{user?.username ?? "-"}</div>
              <div><span className="block text-xs text-slate-400">邮箱</span>{user?.email ?? "-"}</div>
              <div><span className="block text-xs text-slate-400">用户 ID</span>{user?.id ?? "-"}</div>
            </div>
          </SettingsCard>

          <SettingsCard icon={Monitor} title="显示与入口" description="让设置真正影响使用体验：主题、字号密度和默认进入页面。">
            <SelectRow
              label="外观模式"
              hint="系统模式会跟随浏览器或操作系统的深浅色偏好。"
              value={draftSettings.appearance}
              onChange={(value) => updateDraft("appearance", value)}
              options={[{ value: "system", label: "跟随系统" }, { value: "light", label: "浅色" }, { value: "dark", label: "深色" }]}
            />
            <SelectRow
              label="界面字号"
              hint="紧凑适合信息密度高的页面，舒适适合长时间阅读。"
              value={draftSettings.fontScale}
              onChange={(value) => updateDraft("fontScale", value)}
              options={[{ value: "compact", label: "紧凑" }, { value: "default", label: "默认" }, { value: "comfortable", label: "舒适" }]}
            />
            <SelectRow
              label="默认入口"
              hint="用于记录你希望打开系统后优先进入的工作区。"
              value={draftSettings.landingPage}
              onChange={(value) => updateDraft("landingPage", value)}
              options={[{ value: "dashboard", label: "首页概览" }, { value: "knowledge", label: "知识库" }, { value: "notes", label: "笔记" }, { value: "chat", label: "问答" }]}
            />
            <ToggleRow
              label="进入后聚焦搜索"
              hint="适合把系统当作资料检索入口的用户。"
              checked={draftSettings.autoOpenSearch}
              onChange={(value) => updateDraft("autoOpenSearch", value)}
            />
          </SettingsCard>

          <SettingsCard icon={Database} title="知识库默认行为" description="把常见操作前置成偏好，减少每次上传或处理资料时的重复选择。">
            <ToggleRow
              label="上传后自动建议标签"
              hint="开启后，文档处理完成时优先展示系统建议标签。"
              checked={draftSettings.uploadAutoTag}
              onChange={(value) => updateDraft("uploadAutoTag", value)}
            />
            <ToggleRow
              label="显示处理状态提醒"
              hint="文档解析、失败、重试完成时在页面上显示提示。"
              checked={draftSettings.showProcessingToast}
              onChange={(value) => updateDraft("showProcessingToast", value)}
            />
            <ToggleRow
              label="阅读器全屏提示"
              hint="打开 EPUB 或长文档时提示可进入全屏阅读模式。"
              checked={draftSettings.readerFullscreenHint}
              onChange={(value) => updateDraft("readerFullscreenHint", value)}
            />
          </SettingsCard>

          <SettingsCard icon={Bell} title="通知与摘要" description="保留关键事件，避免设置页堆满低价值开关。">
            <ToggleRow
              label="每周知识库摘要"
              hint="汇总本周新增资料、失败任务和高频标签。"
              checked={draftSettings.weeklyDigest}
              onChange={(value) => updateDraft("weeklyDigest", value)}
            />
          </SettingsCard>

          <SettingsCard icon={Shield} title="安全与隐私" description="危险操作必须有保护，敏感元数据也应允许用户隐藏。">
            <ToggleRow
              label="删除前二次确认"
              hint="防止误删文档、标签、集合或笔记。"
              checked={draftSettings.confirmBeforeDelete}
              onChange={(value) => updateDraft("confirmBeforeDelete", value)}
            />
            <ToggleRow
              label="隐藏敏感元数据"
              hint="在列表和预览中弱化原始文件名、路径、上传来源等信息。"
              checked={draftSettings.hideSensitiveMetadata}
              onChange={(value) => updateDraft("hideSensitiveMetadata", value)}
            />
          </SettingsCard>
        </div>

        <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
          <section className="rounded-3xl border border-slate-100 bg-white p-5 shadow-sm shadow-slate-100/60">
            <div className="flex items-center gap-3">
              <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-950 text-sm font-semibold text-white">
                {effectiveName.slice(0, 1).toUpperCase()}
              </span>
              <div className="min-w-0">
                <p className="truncate font-semibold text-slate-900">{effectiveName}</p>
                <p className="truncate text-sm text-slate-500">{user?.email ?? "未绑定邮箱"}</p>
              </div>
            </div>
            <div className="mt-5 space-y-2">
              <SummaryRow label="外观" value={appearanceLabels[draftSettings.appearance]} strong />
              <SummaryRow label="字号" value={fontScaleLabels[draftSettings.fontScale]} />
              <SummaryRow label="默认入口" value={landingPageLabels[draftSettings.landingPage]} />
              <SummaryRow label="删除保护" value={onOff(draftSettings.confirmBeforeDelete)} />
            </div>
          </section>

          <section className="rounded-3xl border border-slate-100 bg-white p-5 shadow-sm shadow-slate-100/60">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-900">当前显示能力</h2>
              <span className={isDirty ? "rounded-full bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700" : "rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700"}>
                {isDirty ? "未保存" : "已同步"}
              </span>
            </div>
            <div className="space-y-2 text-sm">
              <SummaryRow label="聚焦搜索" value={onOff(draftSettings.autoOpenSearch)} />
              <SummaryRow label="自动标签" value={onOff(draftSettings.uploadAutoTag)} />
              <SummaryRow label="处理提醒" value={onOff(draftSettings.showProcessingToast)} />
              <SummaryRow label="每周摘要" value={onOff(draftSettings.weeklyDigest)} />
              <SummaryRow label="隐藏元数据" value={onOff(draftSettings.hideSensitiveMetadata)} />
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}

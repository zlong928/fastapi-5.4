import {
  BookOpen,
  Bot,
  Boxes,
  FileText,
  LayoutGrid,
  Library,
  ListChecks,
  LogOut,
  MessageSquarePlus,
  NotebookText,
  Search,
  Settings,
} from "lucide-react";
import { ComponentType, ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type IconType = ComponentType<{ className?: string }>;

type NavigationItem = {
  href: string;
  label: string;
  icon: IconType;
};

const sidebarItems: NavigationItem[] = [
  { href: "/", label: "首页", icon: LayoutGrid },
  { href: "/knowledge", label: "知识库", icon: Library },
  { href: "/search", label: "搜索", icon: Search },
  { href: "/notes", label: "笔记", icon: NotebookText },
  { href: "/tasks", label: "任务中心", icon: Boxes },
  { href: "/chat", label: "新对话", icon: MessageSquarePlus }
];

const moduleTabs: NavigationItem[] = [
  { href: "/", label: "首页", icon: Bot },
  { href: "/knowledge", label: "知识库", icon: Library },
  { href: "/search", label: "搜索", icon: Search },
  { href: "/notes", label: "笔记", icon: NotebookText },
  { href: "/tasks", label: "任务中心", icon: ListChecks }
];

function WorkspaceLink({ href, label, icon: Icon }: NavigationItem) {
  return (
    <NavLink
      to={href}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-950",
          isActive && "bg-white text-slate-950 shadow-sm ring-1 ring-slate-100"
        )
      }
    >
      <Icon className="h-4 w-4" />
      <span>{label}</span>
    </NavLink>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  function onLogout() {
    logout();
    navigate("/login");
  }

  if (!user) {
    return <main className="min-h-screen bg-white">{children}</main>;
  }

  return (
    <div className="min-h-screen bg-white text-slate-950">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[264px] border-r border-slate-100 bg-slate-50/70 px-3 py-4 lg:flex lg:flex-col">
        <Link to="/knowledge" className="mb-5 flex items-center gap-3 rounded-2xl px-2 py-1.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-white text-xs font-bold shadow-sm ring-1 ring-slate-200">
            KB
          </span>
          <div>
            <p className="text-sm font-semibold leading-tight tracking-tight">Second Brain</p>
            <p className="text-xs text-slate-400">Knowledge Workspace</p>
          </div>
        </Link>

        <nav className="space-y-1">
          {sidebarItems.map((item) => <WorkspaceLink key={item.href} {...item} />)}
        </nav>

        <div className="mt-auto rounded-3xl border border-slate-100 bg-white p-3 shadow-sm">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-full bg-amber-400 font-semibold text-white">
              {user.username?.slice(0, 1).toUpperCase() || "U"}
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{user.username}</p>
              <p className="flex items-center gap-1 text-xs text-slate-500"><span className="h-2 w-2 rounded-full bg-emerald-500" /> 在线</p>
            </div>
          </div>
          <div className="mt-3 space-y-1 border-t border-slate-100 pt-3">
            <Button asChild variant="ghost" className="h-9 w-full justify-start rounded-xl text-slate-700">
              <Link to="/settings"><Settings className="h-4 w-4" />设置</Link>
            </Button>
            <Button type="button" variant="ghost" onClick={onLogout} className="h-9 w-full justify-start rounded-xl text-slate-700">
              <LogOut className="h-4 w-4" />登出
            </Button>
          </div>
        </div>
      </aside>

      <div className="lg:pl-[264px]">
        <header className="sticky top-0 z-20 border-b border-transparent bg-white/90 backdrop-blur">
          <div className="flex h-16 items-center justify-between gap-3 px-5 lg:px-7">
            <Link to="/knowledge" className="flex items-center gap-2 font-semibold lg:hidden">
              <BookOpen className="h-5 w-5" />
              Second Brain
            </Link>
            <nav className="hidden items-center gap-1 overflow-x-auto lg:flex">
              {moduleTabs.map((tab) => (
                <NavLink
                  key={tab.href}
                  to={tab.href}
                  end={tab.href === "/"}
                  className={({ isActive }) =>
                    cn(
                      "inline-flex items-center gap-2 rounded-full px-3 py-2 text-sm font-medium text-slate-400 transition hover:text-slate-900",
                      isActive && "bg-slate-100 text-slate-950"
                    )
                  }
                >
                  {tab.label}
                </NavLink>
              ))}
            </nav>
            <Button asChild size="sm" variant="outline" className="rounded-full px-4">
              <Link to="/knowledge">打开知识库</Link>
            </Button>
          </div>
        </header>

        <main className="mx-auto min-h-[calc(100vh-4rem)] max-w-7xl px-5 py-6 lg:px-7">
          {children}
        </main>
      </div>
    </div>
  );
}

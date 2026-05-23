import {
  BookOpen,
  Boxes,
  LayoutGrid,
  Library,
  LogOut,
  MessageSquare,
  NotebookText,
  Plus,
  RefreshCw,
  Search,
  Settings,
  UploadCloud,
} from "lucide-react";
import { ComponentType, ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
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
  { href: "/tasks", label: "任务", icon: Boxes },
  { href: "/chat", label: "问答", icon: MessageSquare }
];

function WorkspaceLink({ href, label, icon: Icon }: NavigationItem) {
  return (
    <NavLink
      to={href}
      end={href === "/"}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm text-slate-500 transition hover:bg-slate-100 hover:text-slate-950",
          isActive && "bg-white text-slate-950 ring-1 ring-slate-100"
        )
      }
    >
      <Icon className="h-4 w-4" />
      <span>{label}</span>
    </NavLink>
  );
}

function actionForPath(pathname: string) {
  if (pathname.startsWith("/knowledge")) return { href: "/knowledge?upload=1", label: "上传", icon: UploadCloud };
  if (pathname.startsWith("/notes")) return { href: "/notes?new=1", label: "新建", icon: Plus };
  if (pathname.startsWith("/tasks")) return { href: "/tasks", label: "刷新", icon: RefreshCw };
  if (pathname.startsWith("/chat")) return { href: "/chat?new=1", label: "新对话", icon: Plus };
  return { href: "/knowledge", label: "知识库", icon: Library };
}

export function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const pageAction = actionForPath(location.pathname);
  const ActionIcon = pageAction.icon;

  function onLogout() {
    logout();
    navigate("/login");
  }

  if (!user) return <main className="min-h-screen bg-white">{children}</main>;

  return (
    <div className="min-h-screen bg-white text-slate-950">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[220px] border-r border-slate-100 bg-slate-50/60 px-2.5 py-3 lg:flex lg:flex-col">
        <Link to="/knowledge" className="mb-4 flex items-center gap-2 rounded-xl px-2 py-1.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-white text-xs font-semibold ring-1 ring-slate-100">KB</span>
          <span className="truncate text-sm font-semibold tracking-tight">Second Brain</span>
        </Link>

        <nav className="space-y-0.5">
          {sidebarItems.map((item) => <WorkspaceLink key={item.href} {...item} />)}
        </nav>

        <div className="mt-auto space-y-1 border-t border-slate-100 pt-2">
          <div className="flex items-center gap-2 rounded-xl px-2 py-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white">
              {user.username?.slice(0, 1).toUpperCase() || "U"}
            </span>
            <span className="min-w-0 truncate text-sm text-slate-700">{user.username}</span>
          </div>
          <Button asChild variant="ghost" className="h-9 w-full justify-start rounded-xl px-2.5 text-slate-500 hover:text-slate-950">
            <Link to="/settings"><Settings className="h-4 w-4" />设置</Link>
          </Button>
          <Button type="button" variant="ghost" onClick={onLogout} className="h-9 w-full justify-start rounded-xl px-2.5 text-slate-500 hover:text-slate-950">
            <LogOut className="h-4 w-4" />登出
          </Button>
        </div>
      </aside>

      <div className="lg:pl-[220px]">
        <header className="sticky top-0 z-20 bg-white/85 backdrop-blur">
          <div className="flex h-14 items-center justify-between gap-3 px-4 lg:px-6">
            <Link to="/knowledge" className="flex items-center gap-2 text-sm font-semibold lg:hidden">
              <BookOpen className="h-4 w-4" />
              Second Brain
            </Link>
            <div className="hidden lg:block" />
            <Button asChild size="sm" variant="outline" className="h-9 rounded-xl border-slate-100 px-3 text-slate-600 shadow-none">
              <Link to={pageAction.href}>
                <ActionIcon className="h-4 w-4" />
                {pageAction.label}
              </Link>
            </Button>
          </div>
        </header>

        <main className="mx-auto min-h-[calc(100vh-3.5rem)] max-w-7xl px-4 py-5 lg:px-6">
          {children}
        </main>
      </div>
    </div>
  );
}

import { Activity, Library, LayoutDashboard, ListChecks, LogOut, BookOpen } from "lucide-react";
import { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/button";

const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/documents", label: "Documents", icon: BookOpen },
  { href: "/books", label: "Books", icon: Library },
  { href: "/tasks", label: "Task Center", icon: ListChecks }
];

export function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  function onLogout() {
    logout();
    navigate("/login");
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-border bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
          <Link to="/" className="flex items-center gap-2 font-semibold">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-900 text-white">
              <Activity className="h-5 w-5" />
            </span>
            File Processing
          </Link>
          <nav className="flex items-center gap-1">
            {user ? navItems.map((item) => (
              <Button
                asChild
                key={item.href}
                variant="ghost"
                className="gap-2 text-slate-600 hover:text-slate-950"
              >
              <Link to={item.href}>
                <item.icon className="h-4 w-4" />
                <span className="hidden sm:inline">{item.label}</span>
              </Link>
              </Button>
            )) : null}
            {user ? (
              <div className="ml-2 flex items-center gap-2 border-l border-border pl-3">
                <span className="hidden text-sm text-slate-500 md:inline">{user.username}</span>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={onLogout}
                  className="gap-2 text-slate-600 hover:text-slate-950"
                >
                  <LogOut className="h-4 w-4" />
                  <span className="hidden sm:inline">Logout</span>
                </Button>
              </div>
            ) : null}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-5 py-8">{children}</main>
    </div>
  );
}

import { FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await login({ email, password });
      const from = (location.state as { from?: string } | null)?.from ?? "/";
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-md rounded-lg border border-border bg-white p-6 shadow-soft">
      <h1 className="text-2xl font-semibold">Login</h1>
      <p className="mt-2 text-sm text-slate-500">Sign in to upload files and view your private tasks.</p>
      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Email</span>
          <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required className="mt-1 w-full rounded-md border border-border px-3 py-2 outline-none focus:ring-2 focus:ring-slate-300" />
        </label>
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Password</span>
          <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" required className="mt-1 w-full rounded-md border border-border px-3 py-2 outline-none focus:ring-2 focus:ring-slate-300" />
        </label>
        {error ? <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
        <button type="submit" disabled={isSubmitting} className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60">
          {isSubmitting ? "Signing in..." : "Sign in"}
        </button>
      </form>
      <p className="mt-4 text-sm text-slate-500">
        No account yet? <Link to="/register" className="font-medium text-blue-700">Create one</Link>
      </p>
    </div>
  );
}

import { FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { GitHubIcon, GoogleIcon } from "@/components/BrandIcons";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { API_BASE_URL } from "@/lib/api";

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

  function startOAuth(provider: "github" | "google") {
    window.location.href = `${API_BASE_URL}/auth/${provider}/login`;
  }

  return (
    <Card className="mx-auto max-w-md">
      <CardHeader>
        <CardTitle>Login</CardTitle>
        <CardDescription>Sign in to upload files and view your private tasks.</CardDescription>
      </CardHeader>
      <CardContent>
      <form onSubmit={onSubmit} className="space-y-4">
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Email</span>
          <Input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required className="mt-1" />
        </label>
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Password</span>
          <Input value={password} onChange={(event) => setPassword(event.target.value)} type="password" required className="mt-1" />
        </label>
        {error ? (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
        <Button type="submit" disabled={isSubmitting} className="w-full">
          {isSubmitting ? "Signing in..." : "Sign in"}
        </Button>
      </form>
      <div className="my-5 flex items-center gap-3">
        <div className="h-px flex-1 bg-border" />
        <span className="text-xs uppercase tracking-wide text-slate-400">or</span>
        <div className="h-px flex-1 bg-border" />
      </div>
      <div className="space-y-3">
        <Button
          type="button"
          variant="outline"
          onClick={() => startOAuth("github")}
          className="w-full gap-3"
        >
          <GitHubIcon />
          Continue with GitHub
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => startOAuth("google")}
          className="w-full gap-3"
        >
          <GoogleIcon />
          Continue with Google
        </Button>
      </div>
      <p className="mt-4 text-sm text-slate-500">
        No account yet? <Link to="/register" className="font-medium text-blue-700">Create one</Link>
      </p>
      </CardContent>
    </Card>
  );
}

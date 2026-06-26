import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/useAuth";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await register({ email, username, password });
      navigate("/login", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Card className="mx-auto max-w-md">
      <CardHeader>
        <CardTitle>Create account</CardTitle>
        <CardDescription>Use a private account to keep uploads and task results separated.</CardDescription>
      </CardHeader>
      <CardContent>
      <form onSubmit={onSubmit} className="space-y-4">
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Email</span>
          <Input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required className="mt-1" />
        </label>
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Username</span>
          <Input value={username} onChange={(event) => setUsername(event.target.value)} type="text" minLength={2} maxLength={80} required className="mt-1" />
        </label>
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Password</span>
          <Input value={password} onChange={(event) => setPassword(event.target.value)} type="password" minLength={8} required className="mt-1" />
        </label>
        {error ? (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
        <Button type="submit" disabled={isSubmitting} className="w-full">
          {isSubmitting ? "Creating..." : "Create account"}
        </Button>
      </form>
      <p className="mt-4 text-sm text-slate-500">
        Already have an account? <Link to="/login" className="font-medium text-blue-700">Sign in</Link>
      </p>
      </CardContent>
    </Card>
  );
}

import { FormEvent, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { clearToken, resetPassword } from "@/lib/api";

export function ResetPasswordPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const initialEmail = useMemo(() => searchParams.get("email") ?? "", [searchParams]);
  const initialNotice = (location.state as { notice?: string } | null)?.notice ?? null;
  const [email, setEmail] = useState(initialEmail);
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState<string | null>(initialNotice);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setMessage(null);
    setError(null);
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setIsSubmitting(true);
    try {
      await resetPassword({
        email: email.trim().toLowerCase(),
        code,
        new_password: newPassword
      });
      clearToken();
      setMessage("Password reset successfully. Please login again.");
      setTimeout(() => navigate("/login", { replace: true }), 900);
    } catch (err) {
      const fallback = err instanceof Error ? err.message : "Password reset failed.";
      setError(fallback === "Invalid or expired verification code" ? "验证码无效或已过期" : fallback);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Card className="mx-auto max-w-md">
      <CardHeader>
        <CardTitle>Reset password</CardTitle>
        <CardDescription>Use your verification code to set a new password.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4">
          <label className="block">
            <span className="text-sm font-medium text-slate-700">Email</span>
            <Input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required className="mt-1" />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">Verification code</span>
            <Input value={code} onChange={(event) => setCode(event.target.value)} inputMode="numeric" pattern="[0-9]{6}" maxLength={6} required className="mt-1" />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">New password</span>
            <Input value={newPassword} onChange={(event) => setNewPassword(event.target.value)} type="password" minLength={8} required className="mt-1" />
          </label>
          <label className="block">
            <span className="text-sm font-medium text-slate-700">Confirm password</span>
            <Input value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} type="password" minLength={8} required className="mt-1" />
          </label>
          {message ? (
            <Alert>
              <AlertDescription>{message}</AlertDescription>
            </Alert>
          ) : null}
          {error ? (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
          <Button type="submit" disabled={isSubmitting} className="w-full">
            {isSubmitting ? "Resetting..." : "Reset password"}
          </Button>
        </form>
        <p className="mt-4 text-sm text-slate-500">
          Need a new code? <Link to="/forgot-password" className="font-medium text-blue-700">Send again</Link>
        </p>
      </CardContent>
    </Card>
  );
}

import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { forgotPassword } from "@/lib/api";

export function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setMessage(null);
    setError(null);
    setIsSubmitting(true);
    const normalizedEmail = email.trim().toLowerCase();
    try {
      await forgotPassword({ email: normalizedEmail });
      setMessage("If the email exists, a verification code has been sent.");
      navigate(`/reset-password?email=${encodeURIComponent(normalizedEmail)}`, {
        state: { notice: "If the email exists, a verification code has been sent." }
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to send verification code.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Card className="mx-auto max-w-md">
      <CardHeader>
        <CardTitle>Forgot password</CardTitle>
        <CardDescription>Enter your account email to receive a verification code.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4">
          <label className="block">
            <span className="text-sm font-medium text-slate-700">Email</span>
            <Input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required className="mt-1" />
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
            {isSubmitting ? "Sending..." : "Send verification code"}
          </Button>
        </form>
        <p className="mt-4 text-sm text-slate-500">
          Remembered it? <Link to="/login" className="font-medium text-blue-700">Sign in</Link>
        </p>
      </CardContent>
    </Card>
  );
}

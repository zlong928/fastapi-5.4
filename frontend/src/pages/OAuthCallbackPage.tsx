import { useEffect, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "@/auth/useAuth";
import { Card, CardContent } from "@/components/ui/card";
import { setToken } from "@/lib/api";

export function OAuthCallbackPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { refreshUser } = useAuth();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    async function completeLogin() {
      const token = searchParams.get("token");
      if (!token) {
        setFailed(true);
        return;
      }
      setToken(token);
      await refreshUser();
      navigate("/", { replace: true });
    }

    completeLogin();
  }, [navigate, refreshUser, searchParams]);

  if (failed) {
    return <Navigate to="/login?error=oauth_failed" replace />;
  }

  return (
    <Card className="mx-auto max-w-md">
      <CardContent className="p-8 text-slate-500">Completing OAuth login...</CardContent>
    </Card>
  );
}

import { ReactNode, createContext, useEffect, useMemo, useState } from "react";
import { getCurrentUser, getToken, login as loginRequest, logout as logoutRequest, register as registerRequest } from "@/lib/api";
import { LoginRequest, RegisterRequest, UserRead } from "@/lib/types";

export type AuthContextValue = {
  user: UserRead | null;
  isLoading: boolean;
  login: (payload: LoginRequest) => Promise<void>;
  register: (payload: RegisterRequest) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
};

export const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserRead | null>(null);
  const [isLoading, setIsLoading] = useState(Boolean(getToken()));

  async function refreshUser() {
    if (!getToken()) {
      setUser(null);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    try {
      setUser(await getCurrentUser());
    } catch {
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    refreshUser();
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading,
      login: async (payload) => {
        await loginRequest(payload);
        await refreshUser();
      },
      register: async (payload) => {
        await registerRequest(payload);
      },
      logout: () => {
        logoutRequest();
        setUser(null);
      },
      refreshUser
    }),
    [user, isLoading]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

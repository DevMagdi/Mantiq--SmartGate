import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  changePasswordRequest,
  loginRequest,
  logoutRequest,
  meRequest,
} from "@/services/auth";
import {
  clearSession,
  getAccessToken,
  getStoredUser,
  LOGOUT_EVENT,
  saveSession,
  saveUser,
} from "@/services/tokenStore";
import type { User, UserRole } from "@/types/models";

type AuthStatus = "loading" | "authenticated" | "anonymous";

interface AuthContextValue {
  user: User | null;
  status: AuthStatus;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  hasRole: (...roles: UserRole[]) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }): JSX.Element {
  const [user, setUser] = useState<User | null>(() => getStoredUser());
  const [status, setStatus] = useState<AuthStatus>(() =>
    getAccessToken() ? "loading" : "anonymous",
  );

  const logout = useCallback(async () => {
    await logoutRequest();
    clearSession();
    setUser(null);
    setStatus("anonymous");
  }, []);

  const refreshUser = useCallback(async () => {
    try {
      const profile = await meRequest();
      saveUser(profile);
      setUser(profile);
      setStatus("authenticated");
    } catch {
      clearSession();
      setUser(null);
      setStatus("anonymous");
    }
  }, []);

  useEffect(() => {
    if (!getAccessToken()) {
      setStatus("anonymous");
      return;
    }
    void refreshUser();
  }, [refreshUser]);

  useEffect(() => {
    const handleExpiry = (): void => {
      setUser(null);
      setStatus("anonymous");
    };
    window.addEventListener(LOGOUT_EVENT, handleExpiry);
    return () => window.removeEventListener(LOGOUT_EVENT, handleExpiry);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const pair = await loginRequest(email.trim().toLowerCase(), password);
    saveSession(pair);
    setUser(pair.user);
    setStatus("authenticated");
    return pair.user;
  }, []);

  const changePassword = useCallback(
    async (currentPassword: string, newPassword: string) => {
      await changePasswordRequest(currentPassword, newPassword);
    },
    [],
  );

  const hasRole = useCallback(
    (...roles: UserRole[]) => (user ? roles.includes(user.role) : false),
    [user],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      status,
      isAuthenticated: status === "authenticated",
      login,
      logout,
      refreshUser,
      changePassword,
      hasRole,
    }),
    [user, status, login, logout, refreshUser, changePassword, hasRole],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

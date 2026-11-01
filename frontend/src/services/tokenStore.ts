import type { TokenPair, User } from "@/types/models";

const ACCESS_KEY = "gv.access_token";
const REFRESH_KEY = "gv.refresh_token";
const USER_KEY = "gv.user";

export function saveSession(pair: TokenPair): void {
  localStorage.setItem(ACCESS_KEY, pair.access_token);
  localStorage.setItem(REFRESH_KEY, pair.refresh_token);
  localStorage.setItem(USER_KEY, JSON.stringify(pair.user));
}

export function saveUser(user: User): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function getStoredUser(): User | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export function clearSession(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
}

export const LOGOUT_EVENT = "gv:session-expired";

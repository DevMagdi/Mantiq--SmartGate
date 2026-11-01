import { api } from "@/services/api";
import type { MessageResponse } from "@/types/api";
import type { TokenPair, User } from "@/types/models";

export async function loginRequest(email: string, password: string): Promise<TokenPair> {
  const { data } = await api.post<TokenPair>("/auth/login", { email, password });
  return data;
}

export async function meRequest(): Promise<User> {
  const { data } = await api.get<User>("/auth/me");
  return data;
}

export async function changePasswordRequest(
  currentPassword: string,
  newPassword: string,
): Promise<MessageResponse> {
  const { data } = await api.post<MessageResponse>("/auth/change-password", {
    current_password: currentPassword,
    new_password: newPassword,
  });
  return data;
}

export async function logoutRequest(): Promise<void> {
  try {
    await api.post("/auth/logout");
  } catch {
    // Logging out is best-effort; the client drops its tokens either way.
  }
}

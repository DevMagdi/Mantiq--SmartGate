import axios, {
  type AxiosError,
  type InternalAxiosRequestConfig,
} from "axios";

import type { ApiErrorBody, ApiErrorResponse } from "@/types/api";
import type { TokenPair } from "@/types/models";
import {
  clearSession,
  getAccessToken,
  getRefreshToken,
  LOGOUT_EVENT,
  saveSession,
} from "@/services/tokenStore";

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "/api/v1";

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30_000,
  headers: { Accept: "application/json" },
});

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

type RetriableConfig = InternalAxiosRequestConfig & { _retry?: boolean };

let refreshPromise: Promise<string> | null = null;

function expireSession(): void {
  clearSession();
  window.dispatchEvent(new Event(LOGOUT_EVENT));
}

async function refreshAccessToken(): Promise<string> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    throw new Error("No refresh token available");
  }
  const { data } = await axios.post<TokenPair>(`${API_BASE_URL}/auth/refresh`, {
    refresh_token: refreshToken,
  });
  saveSession(data);
  return data.access_token;
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiErrorResponse>) => {
    const original = error.config as RetriableConfig | undefined;
    const status = error.response?.status;
    const url = original?.url ?? "";
    const isAuthCall = url.includes("/auth/login") || url.includes("/auth/refresh");

    if (status === 401 && original && !original._retry && !isAuthCall) {
      if (!getRefreshToken()) {
        expireSession();
        return Promise.reject(error);
      }
      original._retry = true;
      try {
        refreshPromise = refreshPromise ?? refreshAccessToken();
        const token = await refreshPromise;
        refreshPromise = null;
        original.headers.Authorization = `Bearer ${token}`;
        return api(original);
      } catch (refreshError) {
        refreshPromise = null;
        expireSession();
        return Promise.reject(refreshError);
      }
    }
    return Promise.reject(error);
  },
);

export function getApiError(error: unknown): ApiErrorBody {
  if (axios.isAxiosError<ApiErrorResponse>(error)) {
    const body = error.response?.data?.error;
    if (body) return body;
    if (error.code === "ECONNABORTED") {
      return { code: "timeout", message: "The server took too long to respond." };
    }
    if (!error.response) {
      return {
        code: "network_error",
        message: "Cannot reach the GateVision API. Check that the backend is running.",
      };
    }
    return {
      code: `http_${error.response.status}`,
      message: error.message,
    };
  }
  if (error instanceof Error) {
    return { code: "client_error", message: error.message };
  }
  return { code: "unknown_error", message: "Something went wrong." };
}

export function apiErrorMessage(error: unknown): string {
  return getApiError(error).message;
}

/** Resolve a backend media path (e.g. `/media/...`) for the current origin. */
export function mediaUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  const base = import.meta.env.VITE_MEDIA_BASE_URL?.replace(/\/$/, "");
  if (!base || /^https?:\/\//.test(path)) return path;
  return `${base}${path}`;
}

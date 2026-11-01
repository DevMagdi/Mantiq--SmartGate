import { useCallback, useEffect, useRef, useState } from "react";

import type { StreamEvent } from "@/types/api";
import { getAccessToken } from "@/services/tokenStore";

export type ConnectionStatus = "connecting" | "open" | "reconnecting" | "closed";

interface Options {
  gateId?: string;
  limit?: number;
  onEvent?: (event: StreamEvent) => void;
}

interface Result {
  events: StreamEvent[];
  status: ConnectionStatus;
  lastEventAt: string | null;
  clear: () => void;
}

function websocketUrl(token: string, gateId?: string): string {
  const explicit = import.meta.env.VITE_WS_BASE_URL?.replace(/\/$/, "");
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const base = explicit || `${protocol}://${window.location.host}/api/v1`;
  const params = new URLSearchParams({ token });
  if (gateId) params.set("gate_id", gateId);
  return `${base}/ws/events?${params.toString()}`;
}

/** Subscribe to the backend event stream with exponential-backoff reconnects. */
export function useGateEvents({ gateId, limit = 100, onEvent }: Options = {}): Result {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [lastEventAt, setLastEventAt] = useState<string | null>(null);

  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const seenRef = useRef<Set<string>>(new Set());
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<number | null>(null);
  const heartbeatRef = useRef<number | null>(null);
  const attemptsRef = useRef(0);
  const closedRef = useRef(false);

  const clear = useCallback(() => {
    seenRef.current.clear();
    setEvents([]);
  }, []);

  useEffect(() => {
    closedRef.current = false;

    const connect = (): void => {
      const token = getAccessToken();
      if (!token) {
        setStatus("closed");
        return;
      }
      setStatus((current) => (current === "open" ? current : "connecting"));
      const socket = new WebSocket(websocketUrl(token, gateId));
      socketRef.current = socket;

      socket.onopen = () => {
        attemptsRef.current = 0;
        setStatus("open");
        heartbeatRef.current = window.setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) socket.send("ping");
        }, 20_000);
      };

      socket.onmessage = (message) => {
        let parsed: StreamEvent;
        try {
          parsed = JSON.parse(String(message.data)) as StreamEvent;
        } catch {
          return;
        }
        if (parsed.type === "ping") {
          if (socket.readyState === WebSocket.OPEN) socket.send("ping");
          return;
        }
        if (parsed.type === "connected") {
          setStatus("open");
          return;
        }
        if (parsed.id && seenRef.current.has(parsed.id)) return;
        if (parsed.id) seenRef.current.add(parsed.id);
        setLastEventAt(parsed.occurred_at);
        setEvents((current) => [parsed, ...current].slice(0, limit));
        onEventRef.current?.(parsed);
      };

      const scheduleReconnect = (): void => {
        if (closedRef.current) return;
        if (heartbeatRef.current) window.clearInterval(heartbeatRef.current);
        setStatus("reconnecting");
        attemptsRef.current += 1;
        const delay = Math.min(15_000, 1_000 * 2 ** Math.min(attemptsRef.current, 4));
        timerRef.current = window.setTimeout(connect, delay);
      };

      socket.onclose = scheduleReconnect;
      socket.onerror = () => {
        socket.close();
      };
    };

    connect();

    return () => {
      closedRef.current = true;
      if (timerRef.current) window.clearTimeout(timerRef.current);
      if (heartbeatRef.current) window.clearInterval(heartbeatRef.current);
      socketRef.current?.close();
      socketRef.current = null;
      setStatus("closed");
    };
  }, [gateId, limit]);

  return { events, status, lastEventAt, clear };
}

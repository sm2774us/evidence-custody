import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type { Card } from "@/assistant/cards";

export interface Msg { id: string; role: "user" | "assistant"; text?: string; card?: Card; ts: number; pending?: boolean }

interface ChatState {
  messages: Msg[];
  add: (m: Omit<Msg, "id" | "ts">) => string;
  patch: (id: string, m: Partial<Msg>) => void;
  reset: () => void;
}

const uid = () => (globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2));

/** Conversation is per-tab (sessionStorage), capped, and wiped on sign-out. Metadata only, never evidence bytes. */
export const useChat = create<ChatState>()(
  persist(
    (set) => ({
      messages: [],
      add: (m) => { const id = uid(); set((s) => ({ messages: [...s.messages, { ...m, id, ts: Date.now() }].slice(-40) })); return id; },
      patch: (id, m) => set((s) => ({ messages: s.messages.map((x) => (x.id === id ? { ...x, ...m } : x)) })),
      reset: () => set({ messages: [] }),
    }),
    {
      name: "console-chat",
      storage: createJSONStorage(() => sessionStorage),
      partialize: (s) => ({ messages: s.messages.filter((m) => !m.pending) }),
    },
  ),
);

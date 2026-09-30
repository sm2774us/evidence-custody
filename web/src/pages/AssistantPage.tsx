import { useSearch } from "@tanstack/react-router";
import { Bot, RotateCcw, SendHorizonal, User } from "lucide-react";
import { motion } from "motion/react";
import * as React from "react";
import { execute } from "@/assistant/run";
import { SUGGESTIONS, parseIntent } from "@/assistant/intents";
import { useChat } from "@/store/chat";
import { useSession } from "@/store/session";
import { CardView } from "@/components/cards/CardView";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";

export function AssistantPage() {
  const role = useSession((s) => s.identity?.role);
  const { messages, add, patch, reset } = useChat();
  const [text, setText] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const endRef = React.useRef<HTMLDivElement>(null);
  const recall = React.useRef(-1);
  const { q } = useSearch({ strict: false }) as { q?: string };
  const started = React.useRef(false);

  const send = React.useCallback(async (raw: string) => {
    const t = raw.trim();
    if (!t) return;
    setBusy(true); setText(""); recall.current = -1;
    add({ role: "user", text: t });
    const pid = add({ role: "assistant", pending: true });
    const card = await execute(parseIntent(t), role);
    patch(pid, { pending: false, card });
    setBusy(false);
  }, [add, patch, role]);

  React.useEffect(() => { if (q && !started.current) { started.current = true; void send(q); } }, [q, send]);
  React.useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages.length]);

  const history = messages.filter((m) => m.role === "user").map((m) => m.text!);

  return (
    <div className="flex h-[calc(100dvh-8.5rem)] flex-col lg:h-[calc(100dvh-6.5rem)]">
      <div className="mb-3 flex items-center justify-between">
        <div><h1 className="text-xl font-semibold tracking-tight">Assistant</h1><p className="text-sm text-muted-foreground">Ask in plain language. Answers come from the live API; changes need confirmation.</p></div>
        <Button variant="ghost" size="sm" onClick={reset} disabled={!messages.length}><RotateCcw className="size-3.5" /> New chat</Button>
      </div>
      <div role="log" aria-live="polite" aria-label="Conversation" className="min-h-0 flex-1 space-y-4 overflow-y-auto rounded-xl border bg-card/50 p-4">
        {messages.length === 0 ? (
          <div className="mx-auto max-w-xl py-8 text-center">
            <Bot className="mx-auto mb-3 size-10 text-accent" />
            <p className="font-medium">What do you need to know?</p>
            <p className="mt-1 text-sm text-muted-foreground">Try one of these:</p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {["status", "open alerts", "verify audit chain", "help"].map((s) => <Button key={s} variant="outline" size="sm" onClick={() => void send(s)}>{s}</Button>)}
            </div>
          </div>
        ) : null}
        {messages.map((m) => (
          <motion.div key={m.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.15 }} className={`flex gap-3 ${m.role === "user" ? "justify-end" : ""}`}>
            {m.role === "assistant" ? <span className="mt-1 grid size-7 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground"><Bot className="size-4" /></span> : null}
            <div className={`max-w-[92%] rounded-xl px-4 py-3 sm:max-w-[80%] ${m.role === "user" ? "bg-primary text-primary-foreground" : "border bg-card"}`}>
              {m.pending ? <div className="space-y-2" aria-label="Working"><Skeleton className="h-3 w-48" /><Skeleton className="h-3 w-32" /></div>
                : m.card ? <CardView card={m.card} onSend={(t) => void send(t)} /> : <p className="whitespace-pre-wrap text-sm">{m.text}</p>}
            </div>
            {m.role === "user" ? <span className="mt-1 grid size-7 shrink-0 place-items-center rounded-full bg-muted"><User className="size-4" /></span> : null}
          </motion.div>
        ))}
        <div ref={endRef} />
      </div>
      <form className="mt-3 space-y-2" onSubmit={(e) => { e.preventDefault(); if (!busy) void send(text); }}>
        <div className="flex gap-2">
          <label htmlFor="ask" className="sr-only">Message</label>
          <textarea id="ask" rows={1} value={text} disabled={busy} placeholder="e.g. custody report ev_… · why up_… · open alerts"
            className="max-h-32 min-h-11 flex-1 resize-none rounded-xl border bg-background px-4 py-2.5 text-sm"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!busy) void send(text); }
              else if (e.key === "ArrowUp" && !text && history.length) { e.preventDefault(); recall.current = Math.min(recall.current + 1, history.length - 1); setText(history[history.length - 1 - recall.current] ?? ""); }
            }} />
          <Button type="submit" size="icon" className="size-11" disabled={busy || !text.trim()} aria-label="Send"><SendHorizonal className="size-4" /></Button>
        </div>
        <div className="flex flex-wrap gap-1.5">{SUGGESTIONS.slice(0, 4).map((s) => <button key={s} type="button" disabled={busy} onClick={() => void send(s)} className="rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground hover:bg-muted">{s}</button>)}</div>
      </form>
    </div>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  askDataAgent,
  dataAgentConfigured,
  DataAgentNotConfiguredError,
} from '@/services/dataAgent';
import { AssistantContext, type AssistantApi, type Turn } from '@/domain/assistant';
import { frozenAnswer, REPLAY_MS } from '@/services/frozen';
import { deeper, followUps, starters, type Opener } from '@/domain/openers';
import { useQuerySource } from '@/data/querySource';

/**
 * Owns the conversation for the whole console.
 *
 * Mounted once, above the routes, so moving between sections never costs the
 * user their thread.
 */
export function AssistantProvider({ children }: { children: React.ReactNode }) {
  const { preview } = useQuerySource();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [asked, setAsked] = useState<string[]>([]);
  /**
   * The opener the answer on screen came from, so the rail can offer questions that dig into
   * *that* answer. Null after a typed question, which is correct: the console has no depth-2
   * questions for a sentence it did not write.
   */
  const [lastOpener, setLastOpener] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /** Id of the turn currently in flight, so the clock knows what to tick. */
  const runningId = useRef<string | null>(null);
  const seq = useRef(0);

  /**
   * A second-by-second clock, not a timestamp diff on render.
   *
   * Without it the elapsed time only advances when something else re-renders,
   * so a slow agent shows a frozen "0 s" for a minute and reads as a hang.
   */
  useEffect(() => {
    if (!busy) return;
    const t = window.setInterval(() => {
      setTurns((all) =>
        all.map((x) => (x.id === runningId.current ? { ...x, seconds: x.seconds + 1 } : x))
      );
    }, 1000);
    return () => window.clearInterval(t);
  }, [busy]);

  const run = useCallback(
    async (
      question: string,
      prompt: string,
      exercises: string | null,
      openerId?: string
    ) => {
      if (busy) return;
      setBusy(true);
      setLastOpener(openerId ?? null);
      if (openerId) setAsked((a) => [...a, openerId]);

      const id = `turn-${++seq.current}`;
      runningId.current = id;
      setTurns((all) => [
        ...all,
        {
          id,
          question,
          prompt,
          exercises,
          status: 'running',
          progress: 'Sending the question…',
          seconds: 0,
          answer: null,
          error: null,
          replay: null,
        },
      ]);

      const patch = (p: Partial<Turn>) =>
        setTurns((all) => all.map((x) => (x.id === id ? { ...x, ...p } : x)));

      /**
       * The recording is checked before anything is sent.
       *
       * Deliberately in the provider and not in the service: the replay is a *presentation*
       * decision, not a data one, and burying it under `askDataAgent` would make a cached
       * answer indistinguishable from a live one at every call site — including in tests.
       */
      const recorded = frozenAnswer(prompt);
      if (recorded) {
        patch({ progress: 'Reading service figures, XLA clauses and ontology relationships…' });
        await new Promise((r) => setTimeout(r, REPLAY_MS));
        patch({
          status: 'done',
          progress: '',
          replay: { capturedAt: recorded.capturedAt, liveSeconds: recorded.seconds },
          answer: {
            text: recorded.text,
            citations: recorded.citations ?? [],
            toolsFired: recorded.toolsFired,
            durationMs: recorded.seconds * 1000,
            generatedQuery: recorded.generatedQuery,
          },
        });
        runningId.current = null;
        setBusy(false);
        return;
      }

      try {
        // Never send illustrative preview figures to a live agent as measured context.
        if (preview) {
          throw new Error(
            'Open the live app and sign in to ask your own question.',
          );
        }
        const answer = await askDataAgent(prompt, (s) => patch({ progress: s }));
        patch({ status: 'done', answer, progress: '' });
      } catch (err) {
        patch({
          status: 'error',
          progress: '',
          error:
            err instanceof DataAgentNotConfiguredError
              ? 'The Data Agent is not configured in this build. The question above is the one that would be sent to it.'
              : err instanceof Error
                ? err.message
                : String(err),
        });
      } finally {
        runningId.current = null;
        setBusy(false);
      }
    },
    [busy, preview]
  );

  const ask = useCallback(
    (opener: Opener) =>
      void run(opener.label, opener.prompt, opener.exercises, opener.id),
    [run]
  );

  /**
   * Free text goes through unchanged to the Fabric data agent.
   *
   * Unchanged, because dressing a typed question up with schema hints would make the app look
   * cleverer than it is and would silently change what the user asked. The data agent reaches
   * the semantic model, the ontology graph (which carries the XLA clause text) and the
   * Eventhouse, so it covers every question the console asks. The Foundry supervisor shown on
   * the architecture page is simulated in this demo.
   */
  const askText = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      void run(trimmed, trimmed, null);
    },
    [run]
  );

  const value = useMemo<AssistantApi>(
    () => ({
      turns,
      busy,
      deeper: turns.length === 0 ? [] : deeper(lastOpener, asked),
      suggestions: turns.length === 0 ? starters() : followUps(asked),
      configured: dataAgentConfigured(),
      ask,
      askText,
    }),
    [turns, busy, asked, lastOpener, ask, askText]
  );

  return <AssistantContext.Provider value={value}>{children}</AssistantContext.Provider>;
}

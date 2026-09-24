import { createContext, useContext } from 'react';

import type { AgentAnswer } from '@/services/dataAgent';
import type { Opener } from '@/domain/openers';

/**
 * One exchange, as the rail renders it.
 *
 * A turn carries the question **and** the prompt, because they are not the same
 * artefact: `question` is the sentence a human recognises, `prompt` is the
 * table-and-column instruction actually sent to the agent. Collapsing the two
 * would either put schema names in front of the room or hide what was executed,
 * and the second is the kind of quiet dishonesty this app is built to avoid.
 */
export interface Turn {
  id: string;
  question: string;
  prompt: string;
  /** Which parts of the data plane this question exercises, when known. */
  exercises: string | null;
  status: 'running' | 'done' | 'error';
  /** Live status line from the agent poll loop, while running. */
  progress: string;
  /** Wall clock since the question was sent — ticks while running. */
  seconds: number;
  answer: AgentAnswer | null;
  error: string | null;
  /**
   * Set when this turn was served from a recording rather than from a live run.
   *
   * Carried on the turn rather than folded into the answer so the rail is forced to decide
   * what to say about it. A replay that renders identically to a live answer is a lie by
   * omission: same prose, same sources, same badges, but the run never happened. The presence
   * of this field is what makes the disclosure unavoidable.
   */
  replay: { capturedAt: string; liveSeconds: number } | null;
}

export interface AssistantApi {
  turns: Turn[];
  busy: boolean;
  /**
   * The two questions that dig into the answer on screen. Empty before the first answer and
   * after a typed question — see `deeper()` for why that emptiness is not a gap.
   */
  deeper: Opener[];
  /** Other subjects still on the table: starters before the first question, then the rest. */
  suggestions: Opener[];
  /** Whether the Fabric Data Agent is wired in this build. */
  configured: boolean;
  ask: (opener: Opener) => void;
  askText: (text: string) => void;
}

/**
 * The conversation lives above the router.
 *
 * Holding it inside a page would reset it on every navigation, which is exactly
 * the moment a user has most reason to keep it: they clicked through to Impact
 * *because* of the answer they were reading.
 */
export const AssistantContext = createContext<AssistantApi | null>(null);

export function useAssistant(): AssistantApi {
  const api = useContext(AssistantContext);
  if (!api) throw new Error('useAssistant must be used inside <AssistantProvider>.');
  return api;
}

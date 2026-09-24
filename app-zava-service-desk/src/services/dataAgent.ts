/* eslint-disable @typescript-eslint/no-explicit-any -- the preview Data Agent payload is untyped and walked defensively. */
/**
 * Fabric Data Agent client — browser-side.
 *
 * The endpoint is the Fabric OpenAI Assistants-compatible surface, not a chat-completions
 * shortcut. That distinction matters: a natural-language question is first appended to a
 * thread, then a run is started, then the caller polls that run until the Fabric orchestrator
 * has generated and executed the source query. Treating it like one POST would hide the
 * generated KQL/GQL trace and, worse, leave the rail spinning through service-side failures.
 */
import { FABRIC_SCOPES, getToken, msalConfigured } from './msal';
import { getMode } from '../data/mode';

/** A grounding handle exposed by the Data Agent response, when Fabric returns one. */
export interface AgentCitation {
  /** Human-readable citation label; usually a referenced item, table, or annotation text. */
  label: string;
  /** Optional raw detail such as a Fabric item id, item type, URL, or annotation payload. */
  detail?: string;
}

/**
 * Normalized Data Agent answer for the assistant rail.
 *
 * The raw Assistants API response is split across messages and run steps. Returning a small
 * shape here prevents UI code from depending on preview payload details, while still preserving
 * the two things operators need to audit an answer: the generated query and any explicit
 * grounding Fabric exposed.
 */
export interface AgentAnswer {
  /** The assistant prose exactly as returned by Fabric, with no invented provenance. */
  text: string;
  /**
   * Grounding/citation objects exposed by Fabric.
   *
   * This stays empty when the service returns only prose: making up a source would be more
   * misleading than showing none, especially in a demo where trust depends on provenance.
   */
  citations: AgentCitation[];
  /**
   * Which parts of the estate the run actually touched, read back from the run steps.
   *
   * This is the counterweight to the suggestion chips. Every opener declares, before it is
   * sent, which capability it is *expected* to exercise — and that expectation is a guess made
   * by whoever wrote the question. This array is the record of what really happened, and it is
   * allowed to contradict the guess. An empty array is a legitimate, meaningful result: it
   * says the agent answered without consulting anything, which the rail must show rather than
   * quietly present the reply as sourced.
   *
   * Values are whatever Fabric reported, verbatim and de-duplicated. Nothing is invented here.
   */
  toolsFired: string[];
  /** Wall-clock duration of the full thread/message/run/poll/read sequence. */
  durationMs: number;
  /** The generated query, when the agent exposes one (KQL/SQL/DAX). Display only. */
  generatedQuery?: string;
}

/**
 * Thrown only when the build lacks the identifiers or MSAL configuration needed to call Fabric.
 *
 * Other failures are plain `Error`s with human-readable text so the assistant rail can show a
 * retryable service/auth problem without treating it as a configuration defect.
 */
export class DataAgentNotConfiguredError extends Error {
  constructor(message = 'Fabric Data Agent is not configured for this build.') {
    super(message);
    this.name = 'DataAgentNotConfiguredError';
  }
}

const API = 'https://api.fabric.microsoft.com/v1';
const API_VERSION = '2024-02-15-preview';
const STAGE = 'production';
const TIMEOUT_MS = 180_000;
const TERMINAL = new Set(['completed', 'failed', 'cancelled', 'expired']);

const workspaceId = import.meta.env.VITE_ZAVA_WORKSPACE_ID;
const agentId = import.meta.env.VITE_ZAVA_DATA_AGENT_ID;

let threadPromise: Promise<string> | null = null;
let assistantPromise: Promise<string> | null = null;
let askQueue: Promise<void> = Promise.resolve();

/**
 * True when workspace + agent id + MSAL config are all present.
 *
 * This checks configuration only, not reachability. A cheap synchronous gate lets the rail hide
 * the live assistant in builds that cannot possibly call Fabric without accidentally triggering
 * MSAL or a network request during render.
 */
export function dataAgentConfigured(): boolean {
  return Boolean(workspaceId && agentId && msalConfigured);
}

function baseUrl(): string {
  if (!workspaceId || !agentId) throw new DataAgentNotConfiguredError();
  return `${API}/workspaces/${workspaceId}/dataAgents/${agentId}/aiassistant/openai`;
}

function withParams(path: string, extra?: Record<string, string | number>): string {
  const params = new URLSearchParams({ stage: STAGE, 'api-version': API_VERSION });
  for (const [key, value] of Object.entries(extra ?? {})) params.set(key, String(value));
  return `${baseUrl()}${path}?${params.toString()}`;
}

async function fabricFetch<T>(
  path: string,
  init: RequestInit = {},
  extraParams?: Record<string, string | number>
): Promise<T> {
  const token = await getToken(FABRIC_SCOPES, false);
  const res = await fetch(withParams(path, extraParams), {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      ...(init.headers ?? {}),
    },
  });
  const body = await res.text();
  if (!res.ok) throw new Error(`Fabric Data Agent ${res.status}: ${humanBody(body)}`);
  if (!body) return {} as T;
  try {
    return JSON.parse(body) as T;
  } catch {
    throw new Error(`Fabric Data Agent returned non-JSON: ${body.slice(0, 300)}`);
  }
}

async function getThreadId(): Promise<string> {
  if (!threadPromise) {
    threadPromise = fabricFetch<{ id?: string }>('/threads', {
      method: 'POST',
      body: JSON.stringify({}),
    }).then((r) => {
      if (!r.id) throw new Error('Fabric created a thread without returning an id.');
      return r.id;
    });
  }
  return threadPromise;
}

/**
 * Force the next question onto a brand-new thread.
 *
 * Called when a thread is proven unusable. The old thread is not deleted here;
 * `postQuestion` deletes it only when Fabric hands the same locked thread back.
 */
function forgetThread(): void {
  threadPromise = null;
}

/** Delete one of our own threads. DELETE is the one call that rejects `stage`. */
async function deleteThread(threadId: string): Promise<void> {
  const token = await getToken(FABRIC_SCOPES, false);
  const params = new URLSearchParams({ 'api-version': API_VERSION });
  const res = await fetch(`${baseUrl()}/threads/${threadId}?${params.toString()}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`Fabric Data Agent ${res.status}: ${humanBody(await res.text())}`);
}

/** Ask Fabric to stop a run. A run that already finished 400s here; that is a success. */
async function cancelRun(threadId: string, runId: string): Promise<void> {
  try {
    await fabricFetch(`/threads/${threadId}/runs/${runId}/cancel`, { method: 'POST' });
  } catch {
    /* Already terminal, or not cancellable. Either way there is nothing to stop. */
  }
}

/** Poll one run until Fabric reports a terminal status, or the budget runs out. */
async function awaitTerminal(threadId: string, runId: string, budgetMs: number): Promise<boolean> {
  const until = performance.now() + budgetMs;
  for (let attempt = 0; performance.now() < until; attempt += 1) {
    await sleep(pollDelay(attempt));
    try {
      const run = await fabricFetch<any>(`/threads/${threadId}/runs/${runId}`, { method: 'GET' });
      if (TERMINAL.has(String(run?.status ?? ''))) return true;
    } catch {
      // If the run cannot even be read, waiting on it is not going to help.
      return false;
    }
  }
  return false;
}

/**
 * Clear any run still holding the thread lock, before posting a new question.
 *
 * The Assistants surface refuses `POST /messages` while a run is active, and the
 * thread Fabric hands back is sticky across page loads. So a run abandoned by a
 * closed tab — or one that outlived our 180 s poll — keeps rejecting every later
 * question with a 400, permanently, until something cancels it. Nothing in the
 * client did, which is why the rail answered three questions in a row with the
 * same "a run is active" error and never recovered.
 *
 * This is deliberately narrow: it cancels runs on *our* thread only, and only
 * ones Fabric still reports as non-terminal.
 */
async function settleThread(threadId: string, onProgress?: (s: string) => void): Promise<void> {
  let runs: { data?: any[] };
  try {
    runs = await fabricFetch<{ data?: any[] }>(
      `/threads/${threadId}/runs`,
      { method: 'GET' },
      { limit: 5, order: 'desc' }
    );
  } catch {
    return; // Not being able to list runs is not itself a reason to fail the ask.
  }

  const stuck = (runs.data ?? []).filter((r) => r?.id && !TERMINAL.has(String(r?.status ?? '')));
  if (stuck.length === 0) return;

  onProgress?.('Data Agent: clearing a previous run');
  for (const run of stuck) {
    await cancelRun(threadId, run.id);
    await awaitTerminal(threadId, run.id, 20_000);
  }
}

/** The run id Fabric names in "…while a run run_xxx is active". */
function activeRunIdFrom(message: string): string | null {
  return message.match(/\brun_[A-Za-z0-9]+/)?.[0] ?? null;
}

/**
 * Post the question, recovering from the thread lock if we lose the race.
 *
 * `settleThread` handles the common case, but a run can start between that check
 * and this POST. The 400 names the offending run, so the recovery is exact
 * rather than a blind retry: cancel that run, wait for it, post again. If the
 * thread is still refusing after that, it is abandoned for a fresh one.
 */
async function postQuestion(
  threadId: string,
  prompt: string,
  onProgress?: (s: string) => void
): Promise<string> {
  const body = JSON.stringify({ role: 'user', content: prompt });
  try {
    await fabricFetch(`/threads/${threadId}/messages`, { method: 'POST', body });
    return threadId;
  } catch (error) {
    const text = error instanceof Error ? error.message : String(error);
    const blockingRun = activeRunIdFrom(text);
    if (!blockingRun) throw error;

    onProgress?.('Data Agent: cancelling a stuck run');
    await cancelRun(threadId, blockingRun);
    await awaitTerminal(threadId, blockingRun, 30_000);

    try {
      await fabricFetch(`/threads/${threadId}/messages`, { method: 'POST', body });
      return threadId;
    } catch {
      onProgress?.('Data Agent: opening a fresh thread');
      forgetThread();
      let fresh = await getThreadId();
      if (fresh === threadId) {
        // The thread is sticky per user, so asking for a new one returns the locked one again.
        // A lock can outlive its run (the run 404s and never ends); deleting our own thread is
        // the only way past it.
        await deleteThread(threadId);
        forgetThread();
        fresh = await getThreadId();
      }
      await fabricFetch(`/threads/${fresh}/messages`, { method: 'POST', body });
      return fresh;
    }
  }
}

async function getAssistantId(): Promise<string> {
  if (!assistantPromise) {
    assistantPromise = fabricFetch<{ id?: string }>('/assistants', {
      method: 'POST',
      body: JSON.stringify({ model: 'irrelevant' }),
    }).then((r) => {
      if (!r.id) throw new Error('Fabric created an assistant without returning an id.');
      return r.id;
    });
  }
  return assistantPromise;
}

function humanBody(body: string): string {
  try {
    const json = JSON.parse(body);
    return (
      json?.error?.message ??
      json?.message ??
      json?.last_error?.message ??
      JSON.stringify(json).slice(0, 600)
    );
  } catch {
    return body.slice(0, 600);
  }
}

function lastError(run: any): string | null {
  const err = run?.last_error ?? run?.lastError;
  if (!err) return null;
  if (typeof err === 'string') return err;
  return err.message ?? err.code ?? JSON.stringify(err);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function pollDelay(attempt: number): number {
  if (attempt < 2) return 500;
  if (attempt < 4) return 1_000;
  if (attempt < 8) return 2_000;
  return 3_000;
}

async function pollRun(threadId: string, runId: string, started: number, onProgress?: (s: string) => void) {
  let lastStatus = 'created';
  for (let attempt = 0; performance.now() - started < TIMEOUT_MS; attempt += 1) {
    await sleep(pollDelay(attempt));
    const run = await fabricFetch<any>(`/threads/${threadId}/runs/${runId}`, { method: 'GET' });
    const err = lastError(run);
    if (err) throw new Error(`Fabric Data Agent run failed: ${err}`);

    lastStatus = String(run?.status ?? lastStatus);
    onProgress?.(`Data Agent: ${lastStatus}`);
    if (TERMINAL.has(lastStatus)) {
      if (lastStatus === 'completed') return;
      throw new Error(`Fabric Data Agent run ended with status "${lastStatus}".`);
    }
  }
  throw new Error(`Fabric Data Agent timed out after 180s; last observed status was "${lastStatus}".`);
}

function contentText(content: any): string {
  if (typeof content === 'string') return content;
  if (typeof content?.text === 'string') return content.text;
  if (typeof content?.text?.value === 'string') return content.text.value;
  if (typeof content?.value === 'string') return content.value;
  return '';
}

function messageText(message: any): string {
  const content = message?.content;
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return '';
  return content.map(contentText).filter(Boolean).join('\n').trim();
}

function detailOf(value: unknown): string | undefined {
  if (value == null) return undefined;
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function pushCitation(out: AgentCitation[], label: unknown, detail?: unknown): void {
  if (typeof label !== 'string' || !label.trim()) return;
  const citation = { label: label.trim(), detail: detailOf(detail) };
  const key = `${citation.label}\n${citation.detail ?? ''}`;
  if (!out.some((c) => `${c.label}\n${c.detail ?? ''}` === key)) out.push(citation);
}

function collectCitations(value: unknown, out: AgentCitation[] = []): AgentCitation[] {
  if (!value || typeof value !== 'object') return out;
  if (Array.isArray(value)) {
    for (const item of value) collectCitations(item, out);
    return out;
  }

  const obj = value as Record<string, unknown>;
  if (obj.itemReference && typeof obj.itemReference === 'object') {
    const ref = obj.itemReference as Record<string, unknown>;
    pushCitation(out, ref.name ?? ref.displayName ?? ref.itemId, {
      itemId: ref.itemId,
      itemType: ref.itemType,
      workspaceId: ref.workspaceId,
    });
  }
  if (Array.isArray(obj.annotations)) {
    for (const a of obj.annotations as any[]) {
      pushCitation(out, a?.text ?? a?.title ?? a?.label ?? a?.file_citation?.file_id, a);
    }
  }
  if (Array.isArray(obj.citations)) collectCitations(obj.citations, out);
  if (Array.isArray(obj.grounding)) collectCitations(obj.grounding, out);
  if (Array.isArray(obj.references)) collectCitations(obj.references, out);
  for (const nested of Object.values(obj)) collectCitations(nested, out);
  return out;
}

/**
 * Read back which data sources a run genuinely used.
 *
 * The preview payload is not stable enough to pin to one field, so this walks the run steps
 * for the two signals that have actually been observed to carry the answer: the item the step
 * referenced (`itemReference.itemType`, e.g. `Lakehouse` or `KQLDatabase`) and the tool the
 * step invoked (`tool_calls[].type`, or the function name when the type is `function`).
 *
 * Deliberately tolerant on the way in and literal on the way out. An unrecognised name is
 * still evidence and passes through verbatim; translating it into something friendlier here
 * would mean guessing, and a wrong friendly label is worse than an unfamiliar true one. The
 * rail owns presentation.
 */
function collectTools(value: unknown, out: string[] = []): string[] {
  const push = (name: unknown) => {
    if (typeof name !== 'string') return;
    const trimmed = name.trim();
    if (!trimmed || out.includes(trimmed)) return;
    out.push(trimmed);
  };

  if (!value || typeof value !== 'object') return out;
  if (Array.isArray(value)) {
    for (const item of value) collectTools(item, out);
    return out;
  }

  const obj = value as Record<string, unknown>;

  if (obj.itemReference && typeof obj.itemReference === 'object') {
    const ref = obj.itemReference as Record<string, unknown>;
    push(ref.itemType);
  }

  if (Array.isArray(obj.tool_calls)) {
    for (const call of obj.tool_calls as any[]) {
      if (!call || typeof call !== 'object') continue;
      const fn = call.function?.name;
      push(typeof fn === 'string' && fn.trim() ? fn : call.type);
    }
  }

  for (const nested of Object.values(obj)) collectTools(nested, out);
  return out;
}

function fencedQuery(text: string): string | undefined {
  const match = text.match(/```(?:kql|sql|dax|gql)\s*\n([\s\S]*?)```/i);
  return match?.[1]?.trim() || undefined;
}

/**
 * Does this text look like generated query code, as opposed to an answer written for a human?
 *
 * The first version tested `/\b(EVALUATE|SELECT|MATCH|DEFINE|RETURN|SUMMARIZECOLUMNS)\b/i`
 * and, separately, any line starting with a pipe. Both fire on ordinary English: a duty-manager
 * answer that says "the cells **return** to service" matched `RETURN`, and any Markdown table
 * matched the pipe. The whole prose answer was then rendered as code — monospace, with the
 * Markdown asterisks showing literally and a horizontal scrollbar, which is exactly what the
 * operator saw on screen.
 *
 * So the test now looks for query *structure*, not vocabulary:
 *
 *  - DAX and GQL keywords only where generated code puts them — uppercase, opening a line.
 *    Prose neither shouts nor starts a sentence with `EVALUATE`.
 *  - A pipe only when it introduces a real KQL operator. That distinguishes
 *    `| summarize count()` from a Markdown table row, which the old pipe test could not.
 */
const KQL_OPERATOR =
  'where|summarize|project|extend|join|order|sort|take|top|render|distinct|count|' +
  'make-series|mv-expand|parse|union|lookup|evaluate';

const QUERY_SHAPE = [
  /^\s*(EVALUATE|DEFINE|MATCH|SELECT|WITH)\b/m,
  new RegExp(String.raw`\n\s*\|\s*(${KQL_OPERATOR})\b`, 'i'),
];

export function looksLikeQuery(text: string): boolean {
  return QUERY_SHAPE.some((re) => re.test(text));
}

function findGeneratedQuery(value: unknown): string | undefined {
  if (typeof value === 'string') return fencedQuery(value) ?? (looksLikeQuery(value) ? value.trim() : undefined);
  if (!value || typeof value !== 'object') return undefined;
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findGeneratedQuery(item);
      if (found) return found;
    }
    return undefined;
  }

  const obj = value as Record<string, unknown>;
  for (const key of ['daxQuery', 'kqlQuery', 'sqlQuery', 'gqlQuery']) {
    const nested = obj[key] as Record<string, unknown> | undefined;
    if (typeof nested?.query === 'string') return nested.query.trim();
  }
  for (const [key, nested] of Object.entries(obj)) {
    if (/natural|question|prompt/i.test(key)) continue;
    if (/query|code/i.test(key) && typeof nested === 'string') {
      const found = fencedQuery(nested) ?? (looksLikeQuery(nested) ? nested.trim() : undefined);
      if (found) return found;
    }
    const found = findGeneratedQuery(nested);
    if (found) return found;
  }
  return undefined;
}

async function runOnce(prompt: string, onProgress?: (status: string) => void): Promise<AgentAnswer> {
  if (!dataAgentConfigured()) throw new DataAgentNotConfiguredError();
  if (getMode() !== 'live')
    throw new Error('Live mode is disabled, so the Fabric Data Agent was not called.');

  const started = performance.now();
  onProgress?.('Data Agent: creating thread');
  const openThread = await getThreadId();
  const assistantId = await getAssistantId();

  // The thread is sticky across page loads, so it may still be holding a lock
  // from a run nobody is waiting on any more.
  await settleThread(openThread, onProgress);

  onProgress?.('Data Agent: sending question');
  const threadId = await postQuestion(openThread, prompt, onProgress);

  onProgress?.('Data Agent: starting run');
  const run = await fabricFetch<{ id?: string }>(`/threads/${threadId}/runs`, {
    method: 'POST',
    body: JSON.stringify({ assistant_id: assistantId }),
  });
  if (!run.id) throw new Error('Fabric started a run without returning an id.');

  try {
    await pollRun(threadId, run.id, started, onProgress);
  } catch (error) {
    // Our poll gave up, but Fabric's run did not. Leaving it active is what
    // locks the thread for every later question, so stop it on the way out.
    await cancelRun(threadId, run.id);
    throw error;
  }

  onProgress?.('Data Agent: reading answer');
  const [messages, steps] = await Promise.all([
    fabricFetch<{ data?: any[] }>(
      `/threads/${threadId}/messages`,
      { method: 'GET' },
      { limit: 10, order: 'desc' }
    ),
    fabricFetch<{ data?: any[] }>(
      `/threads/${threadId}/runs/${run.id}/steps`,
      { method: 'GET' },
      { limit: 100 }
    ),
  ]);

  const answer = (messages.data ?? []).find((m) => m?.role === 'assistant' && m?.run_id === run.id);
  const text = messageText(answer);
  if (!text) throw new Error('Fabric Data Agent completed but returned no assistant message.');

  const citations = collectCitations(answer);
  collectCitations(steps, citations);

  return {
    text,
    citations,
    toolsFired: collectTools(steps),
    durationMs: Math.round(performance.now() - started),
    // The steps are where a generated query actually lives. The assistant message is prose by
    // construction, so it is searched only for an explicitly fenced block — never sniffed with
    // the shape heuristic, which would be a guess applied to text we already know is a write-up.
    generatedQuery: findGeneratedQuery(steps) ?? fencedQuery(text),
  };
}

/**
 * Ask the Data Agent.
 *
 * The call deliberately uses `getToken(FABRIC_SCOPES, false)`: this function is triggered by a
 * visible UI action, but retries and polling can continue after the browser considers that
 * gesture gone. A popup at that point is usually blocked and leaves the assistant rail looking
 * hung, so callers must surface the auth error and let the user explicitly sign in elsewhere.
 *
 * Questions are also serialized inside this module. Fabric currently reuses a sticky thread and
 * the agent has a per-item run lock; overlapping questions can both succeed while answering the
 * newest prompt instead of their own. A local queue prevents this browser session from creating
 * that cross-talk. The code never pre-emptively deletes a thread: deletion can kill another
 * caller's in-flight run, so stale-thread recovery belongs in an explicit operator action.
 *
 * `onProgress` receives short status strings from the real run so the rail can distinguish a
 * long Fabric hop from a frozen UI.
 */
export async function askDataAgent(
  prompt: string,
  onProgress?: (status: string) => void
): Promise<AgentAnswer> {
  const turn = askQueue.then(() => runOnce(prompt, onProgress));
  askQueue = turn.then(
    () => undefined,
    () => undefined
  );
  return turn;
}

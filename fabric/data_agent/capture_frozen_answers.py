#!/usr/bin/env python3
"""
Record real Data Agent answers so the console's suggested questions are instant.

A live answer from the Fabric Data Agent costs 30-160 seconds: the agent picks a source, writes
the query, Fabric runs it, and only then is there prose. That is the right trade for a genuine
question and the wrong one for the first clicks in front of a room. So the questions the console
itself suggests (openers and their follow-ups) are replayed from a recording, after `REPLAY_MS`,
with a disclosure carrying the capture date and the time the agent really took.

Two rules make that acceptable:

  1. **Nothing here is written by hand.** Every answer comes out of the live
     `ServiceDesk_Analyst` agent, with the sources that really fired, the citations it returned
     and the time it took. An answer where no source fired is REFUSED rather than recorded.
  2. **The questions are derived, never retyped.** The list comes from
     `app-zava-service-desk/src/data/frozen-questions.generated.json`, written by
     `app-zava-service-desk/scripts/freeze-questions.ts` from the TypeScript registry. Replay
     matches on the exact prompt, so a retyped prompt would silently never hit.

The file is written after every answer, and a miss is fail-safe: anything not recorded goes to
the live agent exactly as before.

Usage:
  python -m fabric.data_agent.capture_frozen_answers              # record what is missing
  python -m fabric.data_agent.capture_frozen_answers --force      # re-record everything
  python -m fabric.data_agent.capture_frozen_answers --depth 1    # openers only
  python -m fabric.data_agent.capture_frozen_answers --only xla-breach
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import argparse, json, re, time

import requests
from fabric._shared.helpers import load_state, require_state, get_fabric_token, fabric_headers
from fabric._shared.paths import ROOT

API = "https://api.fabric.microsoft.com/v1"
API_VERSION = "2024-02-15-preview"
# The browser client sends `stage` on every call; without it the endpoints 404.
STAGE = "production"
DATA = ROOT / "app-zava-service-desk" / "src" / "data"
QUESTIONS = DATA / "frozen-questions.generated.json"
ANSWERS = DATA / "frozen-answers.generated.json"

# A run holds a lock on its thread, and `POST /threads` hands back the same thread per user.
RUN_BUDGET_S = 480
TERMINAL = {"completed", "failed", "cancelled", "expired"}

def _url(agent_path: str, path: str) -> str:
    return f"{API}/{agent_path}/aiassistant/openai{path}?stage={STAGE}&api-version={API_VERSION}"


def _call(agent_path: str, path: str, token: str, method: str = "GET", body=None, params=None):
    url = _url(agent_path, path)
    if params:
        url += "&" + "&".join(f"{k}={v}" for k, v in params.items())
    r = requests.request(method, url, headers=fabric_headers(token), json=body, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
    return r.json() if r.text else {}


def replace_thread(agent_path: str, thread_id: str, token: str) -> str:
    """Delete a locked thread and return the fresh one Fabric hands out next.

    DELETE is the one call that rejects `stage` (400 "stage=production is not supported").
    """
    url = f"{API}/{agent_path}/aiassistant/openai/threads/{thread_id}?api-version={API_VERSION}"
    r = requests.delete(url, headers=fabric_headers(token), timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"DELETE /threads/{thread_id} -> {r.status_code}: {r.text[:400]}")
    fresh = _call(agent_path, "/threads", token, "POST", {}).get("id")
    if not fresh or fresh == thread_id:
        raise RuntimeError("Fabric did not hand out a fresh thread after the delete.")
    return fresh


def _walk(value, hit):
    """Depth-first walk over the payload, calling `hit` on every dict.

    The preview payload is not stable enough to pin one field, and the browser client walks it
    the same way for the same reason. Tolerant on the way in, literal on the way out.
    """
    if isinstance(value, list):
        for item in value:
            _walk(item, hit)
    elif isinstance(value, dict):
        hit(value)
        for nested in value.values():
            _walk(nested, hit)


def collect_tools(steps) -> list:
    """Which sources the run genuinely touched: referenced item types and invoked tools."""
    out = []

    def push(name):
        if isinstance(name, str) and name.strip() and name.strip() not in out:
            out.append(name.strip())

    def hit(obj):
        ref = obj.get("itemReference")
        if isinstance(ref, dict):
            push(ref.get("itemType"))
        for call in obj.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            fn = (call.get("function") or {}).get("name")
            push(fn if isinstance(fn, str) and fn.strip() else call.get("type"))

    _walk(steps, hit)
    return out


def collect_citations(*payloads) -> list:
    """Grounding Fabric exposed. Never invented: an empty list stays empty."""
    out = []

    def push(label, detail=None):
        if not isinstance(label, str) or not label.strip():
            return
        item = {"label": label.strip()}
        if detail is not None:
            item["detail"] = detail if isinstance(detail, str) else json.dumps(detail)
        if item not in out:
            out.append(item)

    def hit(obj):
        ref = obj.get("itemReference")
        if isinstance(ref, dict):
            push(ref.get("name") or ref.get("displayName") or ref.get("itemId"),
                 {"itemId": ref.get("itemId"), "itemType": ref.get("itemType"),
                  "workspaceId": ref.get("workspaceId")})
        for a in obj.get("annotations") or []:
            if isinstance(a, dict):
                push(a.get("text") or a.get("title") or a.get("label")
                     or (a.get("file_citation") or {}).get("file_id"), a)

    for p in payloads:
        _walk(p, hit)
    return out


def message_text(message) -> str:
    parts = []
    for block in (message or {}).get("content") or []:
        if isinstance(block, dict):
            text = block.get("text")
            if isinstance(text, dict):
                text = text.get("value")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def find_query(steps) -> str:
    """The generated query, when the run exposes one. Display only."""
    found = []

    def hit(obj):
        for key in ("query", "generatedQuery", "queryText", "kql", "dax", "sql"):
            v = obj.get(key)
            if isinstance(v, str) and v.strip() and len(v.strip()) > 12:
                found.append(v.strip())

    _walk(steps, hit)
    return found[0] if found else ""


def ask(agent_path: str, assistant_id: str, prompt: str, token: str):
    """One question on its own thread. Returns (text, tools, citations, query, seconds)."""
    t0 = time.time()
    thread = _call(agent_path, "/threads", token, "POST", {})
    thread_id = thread.get("id")
    if not thread_id:
        raise RuntimeError("Fabric created a thread without returning an id.")

    # A thread handed back with a run still on it is not usable, and the failure cascades.
    #
    # Observed: a dropped connection left a run active; the next `POST /threads` returned that
    # same thread rather than a fresh one, so every following question in the batch died on
    # "Can't add messages to <thread> while a run <run> is active" -- one blip took out the
    # rest of the run. Fabric names the offending run in the message, so cancel it and carry on
    # rather than reporting a transport hiccup as six broken questions.
    try:
        _call(agent_path, f"/threads/{thread_id}/messages", token, "POST",
              {"role": "user", "content": prompt})
    except RuntimeError as exc:
        stuck = re.search(r"while a run (\S+?) is active", str(exc))
        if not stuck:
            raise
        print(f"        clearing a run left active on the thread ({stuck.group(1)})")
        sys.stdout.flush()
        try:
            _call(agent_path, f"/threads/{thread_id}/runs/{stuck.group(1)}/cancel",
                  token, "POST", {})
        except Exception:  # noqa: BLE001 - already cancelled, or gone; either way, retry below
            pass
        for _ in range(20):
            time.sleep(3)
            try:
                state = _call(agent_path, f"/threads/{thread_id}/runs/{stuck.group(1)}",
                              token).get("status")
            except RuntimeError:
                break  # the run cannot even be read: waiting on it will not help
            if state in TERMINAL:
                break
        try:
            _call(agent_path, f"/threads/{thread_id}/messages", token, "POST",
                  {"role": "user", "content": prompt})
        except RuntimeError as again:
            if "while a run" not in str(again):
                raise
            # A ghost lock: the thread names a run that 404s and never ends. The thread is
            # sticky per user, so `POST /threads` keeps returning it; deleting it is the only
            # way out. It is the caller's own thread, so no one else's run is at stake.
            print("        the lock outlived its run; replacing the thread")
            sys.stdout.flush()
            thread_id = replace_thread(agent_path, thread_id, token)
            _call(agent_path, f"/threads/{thread_id}/messages", token, "POST",
                  {"role": "user", "content": prompt})

    run = _call(agent_path, f"/threads/{thread_id}/runs", token, "POST",
                {"assistant_id": assistant_id})
    run_id = run.get("id")
    if not run_id:
        raise RuntimeError("Fabric started a run without returning an id.")

    status = run.get("status")
    try:
        while status not in TERMINAL:
            if time.time() - t0 > RUN_BUDGET_S:
                raise TimeoutError(f"run still {status} after {RUN_BUDGET_S}s")
            time.sleep(3)
            status = _call(agent_path, f"/threads/{thread_id}/runs/{run_id}", token).get("status")
    except BaseException:
        # Our poll gave up, or the connection dropped under it. Fabric's run did not stop
        # either way, and leaving it active is what locks the thread for everything after.
        try:
            _call(agent_path, f"/threads/{thread_id}/runs/{run_id}/cancel", token, "POST", {})
        except Exception:  # noqa: BLE001 - best effort; the original failure is what matters
            pass
        raise

    if status != "completed":
        raise RuntimeError(f"run ended {status}")

    messages = _call(agent_path, f"/threads/{thread_id}/messages", token,
                     params={"limit": 10, "order": "desc"})
    steps = _call(agent_path, f"/threads/{thread_id}/runs/{run_id}/steps", token,
                  params={"limit": 100})

    answer = next((m for m in messages.get("data") or []
                   if m.get("role") == "assistant" and m.get("run_id") == run_id), None)
    return (message_text(answer), collect_tools(steps),
            collect_citations(answer, steps), find_query(steps),
            round(time.time() - t0, 1))


def main() -> int:
    ap = argparse.ArgumentParser(description="Record live Data Agent answers for replay.")
    ap.add_argument("--force", action="store_true", help="re-record questions already held")
    ap.add_argument("--only", help="limit to one opener id")
    ap.add_argument("--depth", type=int, default=2, help="1 = openers only, 2 = + follow-ups")
    ap.add_argument("--limit", type=int, help="stop after N recordings")
    args = ap.parse_args()

    if not QUESTIONS.exists():
        print(f"!! {QUESTIONS.name} is missing. Generate it first:")
        print("   cd app-zava-service-desk && npx tsx scripts/freeze-questions.ts")
        return 1

    all_entries = json.loads(QUESTIONS.read_text(encoding="utf-8")).get("entries", [])
    entries = [e for e in all_entries
               if e.get("depth", 1) <= args.depth
               and (not args.only or e.get("id") == args.only)
               and e.get("backend", "fabric") == "fabric"]

    payload = {"_comment": "Written by fabric/data_agent/capture_frozen_answers.py, never by "
                           "hand. A missing recording is fail-safe: the question goes to the "
                           "live agent, costing latency and never correctness.",
               "capturedAt": None, "answers": {}}
    if ANSWERS.exists():
        existing = json.loads(ANSWERS.read_text(encoding="utf-8"))
        if existing.get("answers"):
            payload = existing
    payload.setdefault("answers", {})
    answers = payload["answers"]

    # A reworded question leaves its old answer behind, never replayed: prune it.
    live = {e["prompt"] for e in all_entries}
    for p in [p for p in answers if p not in live]:
        print(f"   pruned a recording of a question that no longer exists: "
              f"{answers[p].get('id', '?')}")
        del answers[p]

    todo = [e for e in entries if args.force or e["prompt"] not in answers]
    if args.limit:
        todo = todo[:args.limit]

    print("=" * 78)
    print(f"CAPTURE -- {len(todo)} question(s) to record (of {len(entries)} selected)")
    print("=" * 78)
    if not todo:
        ANSWERS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
        print("\nNothing to do. Use --force to re-record.")
        return 0

    state = load_state()
    workspace_id = require_state(state, "workspace_id")
    agent_id = require_state(state, "data_agent_id")
    agent_path = f"workspaces/{workspace_id}/dataAgents/{agent_id}"
    token = get_fabric_token()
    # POST mints an assistant handle; `model` is required but ignored.
    assistant_id = _call(agent_path, "/assistants", token, "POST", {"model": "irrelevant"}).get("id")
    if not assistant_id:
        print("!! The data agent returned no assistant id. Is it published?")
        return 1

    ok = refused = failed = 0
    for i, e in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}] d{e['depth']} {e['id']:<24} {e['label'][:48]}")
        sys.stdout.flush()
        attempts = 0
        text = None
        while True:
            attempts += 1
            try:
                text, tools, citations, query, secs = ask(agent_path, assistant_id, e["prompt"], token)
                break
            except Exception as exc:  # noqa: BLE001 - several unrelated failure types land here
                blip = ("timeout", "canceled", "cancelled", "ssl", "connection reset",
                        "connection aborted", "max retries", "-> 5")
                if attempts == 1 and any(w in str(exc).lower() for w in blip):
                    print(f"        transport blip ({type(exc).__name__}) - retrying once")
                    token = get_fabric_token()
                    continue
                print(f"        FAILED: {type(exc).__name__}: {str(exc)[:220]}")
                failed += 1
                text = None
                break
        if text is None:
            continue
        if not tools:
            print("        REFUSED: no source fired - the answer is not grounded.")
            refused += 1
            continue
        if not text:
            print("        REFUSED: empty answer.")
            refused += 1
            continue

        record = {"id": e["id"], "depth": e["depth"], "backend": "fabric", "text": text,
                  "toolsFired": tools, "citations": citations, "seconds": secs,
                  "capturedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if query:
            record["generatedQuery"] = query
        answers[e["prompt"]] = record
        payload["capturedAt"] = record["capturedAt"]
        ANSWERS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
        ok += 1
        print(f"        OK {secs}s, {len(text)} chars, sources={tools}, citations={len(citations)}")
        sys.stdout.flush()

    print("\n" + "-" * 78)
    print(f"   {ok} recorded, {refused} refused, {failed} failed, {len(answers)} in the file")
    print(f"   -> {ANSWERS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
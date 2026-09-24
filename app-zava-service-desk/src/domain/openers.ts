/**
 * Questions the user can hand to the assistant.
 *
 * Every opener carries two registers:
 *  - `prompt` — names the table, the measure and the relationship explicitly, so the agent
 *    never has to guess which reading of a service desk phrase we meant.
 *  - `label`  — what the room reads. Plain business language, no identifier.
 *
 * This is not politeness. "Zero-touch this week" has two correct answers: the current ISO
 * week, still open and half empty, and the last closed week, which is the only one an XLA is
 * ever judged on. An unscoped question is under-specified, not unstable — so the prompt says
 * which one.
 *
 * Plain language must not upgrade a claim: a label never says the app *observed* something it
 * merely declares. What actually ran is printed under the answer.
 *
 * Prompts are written in English because the answer comes back in the language it was asked
 * in, and this console is English. The identifiers inside the prompts keep their real
 * spelling: translating `dim_customer` would simply stop it resolving.
 */
export type OpenerFamily =
  | 'portfolio'
  | 'experience'
  | 'live'
  | 'agentops'
  | 'graph'
  | 'contract'
  | 'xla';

/**
 * `mixed` openers force more than one source to fire — a figure from the semantic model *and*
 * a relationship or a clause from the ontology, or a live reading from the Eventhouse.
 *
 * They are the only questions that show what the context layer adds. The entry screen must
 * demonstrate the product, not describe it, so the first card is `mixed`.
 */
export type OpenerKind = 'mixed' | 'single';

/**
 * Which console the question is asked of.
 *
 * One value on purpose. The Fabric data agent `ServiceDesk_Analyst` reaches the semantic model,
 * the ontology (with the XLA clause text) and the Eventhouse, so both the number and the clause
 * come from Fabric. Foundry is part of the story but simulated in this demo: no question is
 * routed to a supervisor that is not deployed. The field stays typed so the capture list keeps
 * recording which console each answer came from.
 */
export type OpenerBackend = 'fabric';

export interface Opener {
  id: string;
  family: OpenerFamily;
  kind: OpenerKind;
  backend: OpenerBackend;
  /**
   * 1 — an entry point, offered before anything has been asked.
   * 2 — digs into the answer a specific depth-1 question just produced.
   */
  depth: 1 | 2;
  /** Depth-2 only: the opener whose answer this one interrogates. */
  parent?: string;
  label: string;
  prompt: string;
  /**
   * One line naming what this question is expected to consult, in service desk language.
   * Shown *before* the question is sent, and contradicted afterwards if the run disagrees.
   */
  exercises: string;
}

/**
 * The house style, appended to every prompt.
 *
 * Written once and shared, because it is a rule about the console rather than a detail of any
 * one question. It describes the **write-up**, never the tooling: telling an agent "never name
 * the tooling" makes it consult nothing.
 */
export const HOUSE_STYLE =
  ' Answer the way a service desk lead prepares a customer call, in 90 words at most: ' +
  'the conclusion first, then only the two or three figures that carry it. ' +
  'Always give a measured value next to its target or its previous value. Do not list rows. ' +
  'In the prose, name customers, sites and agents the way they are said out loud, ' +
  'with no identifier, table name or measure name. Finish with a single `### SOURCE` block ' +
  'of six lines at most, carrying the identifiers, tables, measures and relationships used.';

export const OPENERS: Opener[] = [
  /**
   * First card, and `mixed` on purpose.
   *
   * Two customers fall below the same 40% zero-touch threshold: Fabrikam to 34%, Litware to 38%.
   * One is owed a 9,250 EUR credit, the other a written remediation plan. No figure implies
   * that and no clause implies it either — it only appears when the two are put side by side.
   */
  {
    id: 'xla-breach',
    family: 'xla',
    kind: 'mixed',
    backend: 'fabric',
    depth: 1,
    label: 'Which customers breached an XLA last week, and what does their contract say?',
    prompt:
      'Which customers breached an XLA in the last closed ISO week? Use ' +
      '[XLA Breaches (Last Closed Week)] and [XLA Credit (Last Closed Week)] by ' +
      'dim_customer[customer_name], with [Zero-Touch % (Last Closed Week)] against ' +
      '[Zero-Touch Target %] and [Zero-Touch % (Previous Week)]. For each customer in breach, read the contractual wording in the ' +
      'ontology through (Customer)-[:CustomerHasContract]->(Contract)-[:ContractDefinesXla]->(Xla) ' +
      'and quote Xla.clause_text, then say what the customer is owed.' +
      HOUSE_STYLE,
    exercises: 'the weekly XLA figures, then the contract clauses',
  },
  {
    id: 'xla-fabrikam-credit',
    family: 'xla',
    kind: 'single',
    backend: 'fabric',
    depth: 2,
    parent: 'xla-breach',
    label: 'How big is the Fabrikam drop, and how was the credit worked out?',
    prompt:
      'For dim_customer[customer_name] = "Fabrikam Industries", give ' +
      '[Zero-Touch % (Previous Week)], [Zero-Touch % (Last Closed Week)], ' +
      '[Zero-Touch Change (pts)], [Tickets (Last Closed Week)], [Zero-Touch Target %] and ' +
      '[XLA Credit (Last Closed Week)]. Explain the credit as a share of the monthly fee and ' +
      'say whether the monthly cap is reached. Do not recompute the credit.' +
      HOUSE_STYLE,
    exercises: 'the weekly zero-touch and credit figures',
  },
  {
    id: 'xla-litware-contrast',
    family: 'xla',
    kind: 'mixed',
    backend: 'fabric',
    depth: 2,
    parent: 'xla-breach',
    label: 'Litware missed the target too. Why is no credit due?',
    prompt:
      'Compare dim_customer[customer_name] = "Litware Insurance" with "Fabrikam Industries" on ' +
      '[Zero-Touch % (Previous Week)], [Zero-Touch % (Last Closed Week)], ' +
      '[XLA Breaches (Last Closed Week)] and [XLA Credit (Last Closed Week)]. Then read both ' +
      'zero-touch clauses through (Customer)-[:CustomerHasContract]->(Contract)-[:ContractDefinesXla]->(Xla) ' +
      "where Xla.metric = 'zero_touch_rate', and explain why the same breach has a different " +
      'consequence.' +
      HOUSE_STYLE,
    exercises: 'the weekly figures of both customers, then both clauses',
  },

  {
    id: 'experience-worst-site',
    family: 'experience',
    kind: 'single',
    backend: 'fabric',
    depth: 1,
    label: 'Which site has the worst digital experience?',
    prompt:
      'Which three sites have the lowest [Experience Score]? Rank dim_site[site_name] by ' +
      '[Experience Score] ascending and give [VPN Latency (ms)], [Teams MOS] and ' +
      '[App Crashes] for each.' +
      HOUSE_STYLE,
    exercises: 'the daily experience figures by site',
  },
  {
    id: 'experience-lyon-cause',
    family: 'experience',
    kind: 'mixed',
    backend: 'fabric',
    depth: 2,
    parent: 'experience-worst-site',
    label: 'What is causing it, and who is affected?',
    prompt:
      'For the worst site, find the open major incident through ' +
      '(MajorIncident)-[:MajorIncidentAffectsSite]->(Site) and the application behind it through ' +
      '(MajorIncident)-[:MajorIncidentCausedByApp]->(Application); give MajorIncident.root_cause ' +
      'and MajorIncident.severity as recorded. ' +
      'Then count the affected users and VIPs with [Impacted Users] and [Impacted VIP Users].' +
      HOUSE_STYLE,
    exercises: 'the incident map, then the impact figures',
  },
  {
    id: 'experience-lyon-now',
    family: 'experience',
    kind: 'mixed',
    backend: 'fabric',
    depth: 2,
    parent: 'experience-worst-site',
    label: 'Is Lyon still degraded in the live telemetry?',
    prompt:
      'In the Eventhouse table dem_telemetry, anchored on max(timestamp), give the average ' +
      'experience_score and vpn_latency_ms for site_id "FAB-LYO" over the last hour, split by ' +
      'vpn_client_version. Compare with the closed-day [Experience Score] of the Lyon site, and ' +
      'say plainly that the two cover different windows.' +
      HOUSE_STYLE,
    exercises: 'the live device telemetry, then the daily experience figures',
  },

  {
    id: 'agentops-escalations',
    family: 'agentops',
    kind: 'single',
    backend: 'fabric',
    depth: 1,
    label: 'How much are the AI agents resolving on their own?',
    prompt:
      'By dim_agent[agent_name] and dim_agent[agent_type], give [Tickets], ' +
      '[Zero-Touch Tickets] and [HITL Escalations], keeping only agents with at least one ' +
      'ticket. Say which AI agent hands the most tickets to humans.' +
      HOUSE_STYLE,
    exercises: 'the ticket figures by agent',
  },
  {
    id: 'agentops-tool-failures',
    family: 'agentops',
    kind: 'mixed',
    backend: 'fabric',
    depth: 2,
    parent: 'agentops-escalations',
    label: 'Which tool is failing, and for which customer?',
    prompt:
      'In the Eventhouse table agent_traces, anchored on max(timestamp), count spans with ' +
      'status == "error" over the last 24 hours by customer_id, tool_name and error_type. Then ' +
      'give [HITL Escalations] and [Zero-Touch % (Last Closed Week)] for the customer with the ' +
      'most failures.' +
      HOUSE_STYLE,
    exercises: 'the live agent traces, then the weekly escalation figures',
  },
  {
    id: 'agentops-throttling',
    family: 'agentops',
    kind: 'single',
    backend: 'fabric',
    depth: 2,
    parent: 'agentops-escalations',
    label: 'Is the AI gateway throttling the agents?',
    prompt:
      'In the Eventhouse table gateway_logs, anchored on max(timestamp), give requests and ' +
      'requests with status_code == 429 over the last 24 hours by customer_id and model, with ' +
      'the throttled share.' +
      HOUSE_STYLE,
    exercises: 'the live AI gateway logs',
  },

  {
    id: 'portfolio-week',
    family: 'portfolio',
    kind: 'single',
    backend: 'fabric',
    depth: 1,
    label: 'How did each customer do last week against the week before?',
    prompt:
      'By dim_customer[customer_name], give [Zero-Touch % (Last Closed Week)], ' +
      '[Zero-Touch % (Previous Week)], [Zero-Touch Change (pts)] and ' +
      '[Tickets (Last Closed Week)]. Say which customers moved the most.' +
      HOUSE_STYLE,
    exercises: 'the weekly service figures by customer',
  },
  {
    id: 'portfolio-csat',
    family: 'portfolio',
    kind: 'single',
    backend: 'fabric',
    depth: 2,
    parent: 'portfolio-week',
    label: 'Where are satisfaction and time lost worst?',
    prompt:
      'By dim_customer[customer_name], give [CSAT Avg], [CSAT Responses], ' +
      '[Time Lost per Seat (min)] and [MTTR (h)]. Say which customer has the lowest ' +
      'satisfaction and which loses the most time per seat.' +
      HOUSE_STYLE,
    exercises: 'the satisfaction and time-lost figures',
  },
  {
    id: 'portfolio-threshold',
    family: 'portfolio',
    kind: 'mixed',
    backend: 'fabric',
    depth: 2,
    parent: 'portfolio-week',
    label: 'Who is closest to their zero-touch threshold?',
    prompt:
      'Read each zero-touch threshold through ' +
      '(Customer)-[:CustomerHasContract]->(Contract)-[:ContractDefinesXla]->(Xla) where ' +
      "Xla.metric = 'zero_touch_rate', then compare it with [Zero-Touch % (Last Closed Week)] " +
      'by dim_customer[customer_name]. Rank customers by the margin left above the threshold.' +
      HOUSE_STYLE,
    exercises: 'the contract thresholds, then the weekly figures',
  },

  {
    id: 'graph-user-covered',
    family: 'graph',
    kind: 'single',
    backend: 'fabric',
    depth: 1,
    label: 'A Fabrikam user is calling. Is a known incident already covering them?',
    prompt:
      'Is user USR-FAB-0061 affected by an open major incident? Traverse ' +
      '(User)<-[:SiteHostsUser]-(Site)<-[:MajorIncidentAffectsSite]-(MajorIncident) ' +
      "where MajorIncident.status = 'open', and give the user's site, whether they are a VIP, " +
      'and the incident title and severity.' +
      HOUSE_STYLE,
    exercises: 'the user, site and incident map',
  },
  {
    id: 'graph-vips',
    family: 'graph',
    kind: 'single',
    backend: 'fabric',
    depth: 2,
    parent: 'graph-user-covered',
    label: 'Which VIPs does that incident reach?',
    prompt:
      'For major incident MI-FAB-0001, traverse (MajorIncident)-[:MajorIncidentAffectsSite]->' +
      '(Site)-[:SiteHostsUser]->(User) where User.is_vip = true, and give how many VIPs are ' +
      'affected and their departments, next to the number of users the incident reaches at ' +
      'that site. There is no VIP target: compare VIPs with all users affected.' +
      HOUSE_STYLE,
    exercises: 'the incident, site and user map',
  },
  {
    id: 'graph-tickets',
    family: 'graph',
    kind: 'mixed',
    backend: 'fabric',
    depth: 2,
    parent: 'graph-user-covered',
    label: 'How many tickets did it generate, and what did that do to zero-touch?',
    prompt:
      'Count the tickets linked to major incident MI-FAB-0001 through ' +
      '(Ticket)-[:TicketPartOfIncident]->(MajorIncident). Then give ' +
      '[Zero-Touch % (Previous Week)] and [Zero-Touch % (Last Closed Week)] for ' +
      'dim_customer[customer_name] = "Fabrikam Industries", and relate the two.' +
      HOUSE_STYLE,
    exercises: 'the ticket map, then the weekly zero-touch figures',
  },

  {
    id: 'live-vpn',
    family: 'live',
    kind: 'single',
    backend: 'fabric',
    depth: 1,
    label: 'What does VPN latency look like, site by site, right now?',
    prompt:
      'In the Eventhouse table dem_telemetry, anchored on max(timestamp), give the p50 and p95 ' +
      'of vpn_latency_ms, the average experience_score and the device count over the last hour, ' +
      'by site_id and customer_id, worst first.' +
      HOUSE_STYLE,
    exercises: 'the live device telemetry',
  },
  {
    id: 'live-csat',
    family: 'live',
    kind: 'single',
    backend: 'fabric',
    depth: 2,
    parent: 'live-vpn',
    label: 'What are users saying in the last 24 hours?',
    prompt:
      'In the Eventhouse tables csat_events and conversations, anchored on max(timestamp), give ' +
      'the average CSAT score and the share of negative conversation turns (a turn is negative ' +
      'when its real-valued sentiment, between -1 and 1, is below 0) over the ' +
      'last 24 hours, by customer_id. There is no contractual target on these: compare each ' +
      'customer with the all-customer figure over the same 24 hours.' +
      HOUSE_STYLE,
    exercises: 'the live survey and conversation streams',
  },
  {
    id: 'live-vs-closed',
    family: 'live',
    kind: 'mixed',
    backend: 'fabric',
    depth: 2,
    parent: 'live-vpn',
    label: 'How does the last hour compare with the closed days?',
    prompt:
      'For the site with the highest live p95 vpn_latency_ms in dem_telemetry over the last ' +
      'hour, compare with its closed-day [VPN Latency (ms)] and [Experience Score] from the ' +
      'semantic model, and say plainly that the two cover different windows.' +
      HOUSE_STYLE,
    exercises: 'the live telemetry, then the daily experience figures',
  },

  {
    id: 'contract-zero-touch',
    family: 'contract',
    kind: 'single',
    backend: 'fabric',
    depth: 1,
    label: 'What does each contract promise on zero-touch?',
    prompt:
      'List every zero-touch XLA through ' +
      '(Customer)-[:CustomerHasContract]->(Contract)-[:ContractDefinesXla]->(Xla) where ' +
      "Xla.metric = 'zero_touch_rate': customer, comparator, threshold, measurement window, " +
      'penalty_pct and a short quote of clause_text. Group them by consequence and count ' +
      'the XLAs in each group, so the groups add up to the total.' +
      HOUSE_STYLE,
    exercises: 'the contract clauses',
  },
  {
    id: 'contract-caps',
    family: 'contract',
    kind: 'single',
    backend: 'fabric',
    depth: 2,
    parent: 'contract-zero-touch',
    label: 'How are credits capped, contract by contract?',
    prompt:
      'Through (Customer)-[:CustomerHasContract]->(Contract), give Contract.monthly_fee_eur and ' +
      'Contract.penalty_cap_pct for every customer, and the monthly maximum credit it implies.' +
      HOUSE_STYLE,
    exercises: 'the contract terms',
  },
  {
    id: 'contract-measured',
    family: 'contract',
    kind: 'mixed',
    backend: 'fabric',
    depth: 2,
    parent: 'contract-zero-touch',
    label: 'Where does each customer sit against those promises?',
    prompt:
      'Read the CSAT and zero-touch thresholds through ' +
      '(Customer)-[:CustomerHasContract]->(Contract)-[:ContractDefinesXla]->(Xla), then give ' +
      '[Zero-Touch % (Last Closed Week)], [Zero-Touch Target %], [XLA Breaches (Last Closed Week)] ' +
      'and [CSAT Avg] by dim_customer[customer_name], and flag every customer below a threshold.' +
      HOUSE_STYLE,
    exercises: 'the contract clauses, then the measured figures',
  },
];

/**
 * How each family presents itself.
 *
 * Kept beside the openers for the same reason `severity.ts` owns its colour map: two screens
 * that each invent an icon for "XLA" drift apart within a week. `area` is the human name of
 * the investigation, not the technical family key.
 */
export const FAMILY_STYLE: Record<
  OpenerFamily,
  { icon: string; accent: string; area: string }
> = {
  portfolio: { icon: '🎯', accent: '#00008F', area: 'Portfolio' },
  experience: { icon: '💻', accent: '#027180', area: 'Experience' },
  live: { icon: '📡', accent: '#0891b2', area: 'Live telemetry' },
  agentops: { icon: '🤖', accent: '#5b21b6', area: 'AI agents' },
  graph: { icon: '🕸️', accent: '#0369a1', area: 'Impact map' },
  contract: { icon: '📜', accent: '#896610', area: 'Contracts' },
  xla: { icon: '💶', accent: '#863C41', area: 'XLA & credits' },
};

/**
 * One opener per family — never `slice(0, n)`.
 *
 * A cap over a curated list does not sample it, it truncates it, and it fails silently. The
 * test pins **family coverage**, not the count.
 */
export function selectOpeners(pool: Opener[] = OPENERS): Opener[] {
  const seen = new Set<OpenerFamily>();
  const picked: Opener[] = [];
  for (const o of pool) {
    if (seen.has(o.family)) continue;
    seen.add(o.family);
    picked.push(o);
  }
  return picked;
}

/** Entry points only. A depth-2 question as a first card assumes a figure nobody has seen. */
export function entryPoints(pool: Opener[] = OPENERS): Opener[] {
  return pool.filter((o) => o.depth === 1);
}

/** Before the first question: 3 starters. More is a decision, and a live demo stalls on it. */
export function starters(pool: Opener[] = OPENERS): Opener[] {
  return selectOpeners(entryPoints(pool)).slice(0, 3);
}

/**
 * The two questions that dig into the answer just given.
 *
 * Returns nothing for a typed question, and nothing once both have been asked.
 */
export function deeper(
  lastOpenerId: string | null,
  asked: string[],
  pool: Opener[] = OPENERS
): Opener[] {
  if (!lastOpenerId) return [];
  const askedSet = new Set(asked);
  return pool.filter(
    (o) => o.depth === 2 && o.parent === lastOpenerId && !askedSet.has(o.id)
  );
}

/**
 * The other subjects still on the table, minus what was already asked.
 *
 * Kept alongside `deeper`: a rail that only ever digs walks the room down one branch and never
 * shows the graph, the contracts or the live stream.
 */
export function followUps(asked: string[], pool: Opener[] = OPENERS): Opener[] {
  const askedSet = new Set(asked);
  const remaining = entryPoints(pool).filter((o) => !askedSet.has(o.id));
  const perFamily = selectOpeners(remaining);
  const extra = remaining.filter((o) => !perFamily.includes(o));
  return [...perFamily, ...extra].slice(0, 3);
}

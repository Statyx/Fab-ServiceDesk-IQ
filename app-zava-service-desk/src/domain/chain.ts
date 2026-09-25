/**
 * The deployed chain, declared once.
 *
 * A sibling console derives this from a live tenant probe and prints "8/8 components observed".
 * This one does not, and the difference is deliberate: a claim of observation that nothing
 * actually observed is worse than no claim at all. Every field below is a statement about what
 * was deployed, and the page says exactly that — nothing here reports a health check.
 *
 * The Foundry plane is the target architecture the Zava IQ page tells: a supervisor that asks the
 * Fabric data agent for the figures, a contract agent that retrieves the clause from a Foundry IQ
 * knowledge base over the six service agreements, and Work IQ and Web IQ for what is underway and
 * what is public. In this demo that plane is not deployed: the console asks the data agent
 * directly and the clause is read from the ontology (`Xla.clause_text`). The screen does not say
 * so — the presenter does (docs/demo/DEMO_SCRIPT.html) — and nothing on it pretends to a health
 * check either.
 *
 * `row` is data, not insertion order. The renderer places a node at `row` within its `layer`,
 * and the rows are chosen so no two hops cross: the contract agent sits above the Work IQ and
 * Web IQ tools and above the analyst, and its knowledge base sits above the three stores the
 * analyst reads, in the order it reaches them. Everything else that reads the Eventhouse sits
 * below, and the live signals that feed it sit last, so the real-time hops fan into one box
 * without crossing. In a picture whose whole job is "who talks to what", a crossing reads as a
 * wiring mistake.
 *
 * The real-time plane is drawn in full because it is half of the demo: the data agent reads the
 * Eventhouse in KQL when a question says "right now", and the reactive loop (Activator watching
 * the stream, the operations agent proposing an action) never goes through the data agent.
 */
export type Plane = 'foundry' | 'fabric' | 'semantic' | 'ontology' | 'realtime';

export interface ChainNode {
  id: string;
  label: string;
  /** One line inside the box. Kept short — SVG text does not wrap, it collides. */
  detail: string;
  plane: Plane;
  layer: number;
  row: number;
  /** The long version, shown on hover and in the list under the diagram. */
  role: string;
}

export interface ChainEdge {
  from: string;
  to: string;
  /** How the hop is made. Printed in bold above the arrow. */
  protocol: string;
  /** What it carries, when the protocol alone is not enough. */
  short?: string;
}

export const CHAIN_NODES: ChainNode[] = [
  {
    id: 'supervisor',
    label: 'Zava-ServiceDesk-Agent',
    detail: 'orchestration',
    plane: 'foundry',
    layer: 0,
    row: 0,
    role: 'Foundry supervisor. Dispatches the question to the data agent, the contract agent, Work IQ and Web IQ, and reconciles the answers; computes nothing itself.',
  },
  {
    id: 'contracts',
    label: 'Zava-SD-Contracts',
    detail: 'contract agent',
    plane: 'foundry',
    layer: 1,
    row: 0,
    role: 'Foundry contract agent. Retrieves and cites the applicable XLA clause and its consequence (credit, remediation plan, reported only). Computes nothing.',
  },
  {
    id: 'workiq',
    label: 'Work IQ',
    detail: 'mail, Teams, meetings',
    plane: 'foundry',
    layer: 1,
    row: 1,
    role: 'Work IQ. What is already underway on the account and who owns the next step: escalations, meetings, the service manager to write to.',
  },
  {
    id: 'webiq',
    label: 'Web IQ',
    detail: 'public announcements',
    plane: 'foundry',
    layer: 1,
    row: 2,
    role: 'Web IQ. What the customer has said in public that gives the service review more context.',
  },
  {
    id: 'corpus',
    label: 'Service agreements',
    detail: 'Foundry IQ · 6 contracts',
    plane: 'foundry',
    layer: 2,
    row: 0,
    role: 'Foundry IQ knowledge base. The six signed managed service agreements (CTR-FAB-2026 to CTR-WOO-2026), searched as text. No figure is stored here.',
  },
  {
    id: 'analyst',
    label: 'ServiceDesk_Analyst',
    detail: 'data agent · DAX, GQL, KQL',
    plane: 'fabric',
    layer: 1,
    row: 3,
    role: 'Fabric data agent. Reads the measures, traverses the graph and, for anything "right now", queries the Eventhouse in KQL. Computes no credit itself.',
  },
  {
    id: 'ops',
    label: 'OA_ServiceDesk_Ops',
    detail: 'operations agent · 4 goals',
    plane: 'realtime',
    layer: 3,
    row: 1,
    role: 'Fabric operations agent: the reactive one. Watches the live telemetry against four goals (VPN latency, experience score, agent errors, gateway 429) and proposes an action.',
  },
  {
    id: 'activator',
    label: 'ACT_ServiceDesk_Alerts',
    detail: 'Activator · VPN > 200 ms',
    plane: 'realtime',
    layer: 3,
    row: 2,
    role: 'Activator. Evaluates dem_telemetry every 60 s, per site, and alerts Teams when the 5-minute VPN latency average goes above 200 ms. Deployed stopped.',
  },
  {
    id: 'dashboard',
    label: 'RTD_ServiceDesk_Operations',
    detail: 'RTI dashboard · 2 pages',
    plane: 'realtime',
    layer: 3,
    row: 3,
    role: 'Real-Time dashboard, pages Operations and AgentOps. Every tile is a KQL query anchored on the latest timestamp.',
  },
  {
    id: 'signals',
    label: 'Live signals',
    detail: 'scenario injector · 6 streams',
    plane: 'realtime',
    layer: 1,
    row: 4,
    role: 'Device telemetry, agent spans, gateway logs, ticket, conversation and CSAT events, pushed by the scenario injector. Real streaming ingestion.',
  },
  {
    id: 'semantic',
    label: 'SM_ServiceDesk_Analytics',
    detail: '28 measures — every figure',
    plane: 'semantic',
    layer: 2,
    row: 1,
    role: 'Semantic model. The single definition of every figure the console prints, credits included.',
  },
  {
    id: 'ontology',
    label: 'ONT_ServiceDesk',
    detail: '13 entities · XLA clauses',
    plane: 'ontology',
    layer: 2,
    row: 2,
    role: 'Ontology. Answers user - site - incident by traversal, and carries the contractual wording of every XLA.',
  },
  {
    id: 'realtime',
    label: 'EH_ServiceDesk',
    detail: 'KQL database · 6 live tables',
    plane: 'realtime',
    layer: 2,
    row: 3,
    role: 'Eventhouse. What is happening right now: device telemetry, agent traces, gateway logs, tickets, conversations and surveys as they arrive.',
  },
  {
    id: 'lakehouse',
    label: 'LH_ServiceDesk',
    detail: '21 Delta tables',
    plane: 'fabric',
    layer: 3,
    row: 0,
    role: 'Lakehouse. One copy of the closed-period data, read in place by the model and the ontology.',
  },
];

export const CHAIN_EDGES: ChainEdge[] = [
  { from: 'supervisor', to: 'contracts', protocol: 'A2A', short: 'the clause' },
  { from: 'supervisor', to: 'workiq', protocol: 'MCP', short: 'Microsoft 365' },
  { from: 'supervisor', to: 'webiq', protocol: 'Tool', short: 'web grounding' },
  { from: 'supervisor', to: 'analyst', protocol: 'A2A', short: 'the figures' },
  { from: 'contracts', to: 'corpus', protocol: 'Foundry IQ', short: 'retrieval' },
  { from: 'analyst', to: 'semantic', protocol: 'DAX' },
  { from: 'analyst', to: 'ontology', protocol: 'GQL' },
  { from: 'analyst', to: 'realtime', protocol: 'KQL', short: 'right now' },
  { from: 'realtime', to: 'ops', protocol: 'KQL', short: '4 goals' },
  { from: 'realtime', to: 'activator', protocol: 'KQL', short: 'every 60 s' },
  { from: 'realtime', to: 'dashboard', protocol: 'KQL', short: 'tiles' },
  { from: 'signals', to: 'realtime', protocol: 'Streaming', short: 'ingestion' },
  { from: 'semantic', to: 'lakehouse', protocol: 'Direct Lake' },
  { from: 'ontology', to: 'lakehouse', protocol: 'Delta' },
];

export const PLANE_LABEL: Record<Plane, string> = {
  foundry: 'Foundry — agents, Foundry IQ',
  fabric: 'Fabric — agent, lakehouse',
  semantic: 'Semantic model (DAX)',
  ontology: 'Ontology (GQL)',
  realtime: 'Real-Time Intelligence (KQL)',
};
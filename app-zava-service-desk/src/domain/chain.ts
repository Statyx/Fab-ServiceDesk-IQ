/**
 * The deployed chain, declared once.
 *
 * A sibling console derives this from a live tenant probe and prints "8/8 components observed".
 * This one does not, and the difference is deliberate: a claim of observation that nothing
 * actually observed is worse than no claim at all. Every field below is a statement about what
 * was deployed, and the page says exactly that — nothing here reports a health check.
 *
 * One box is not deployed, and says so. The Foundry supervisor is part of the story — it is
 * where the service desk's own agents would call Fabric from — but in this demo it is
 * **simulated**: the console talks to the Fabric data agent directly. Drawing it as if it ran
 * would be the exact quiet overstatement the app exists to avoid.
 *
 * `row` is data, not insertion order. The renderer places a node at `row` within its `layer`,
 * and the rows are chosen so no two hops cross: the analyst sits above the operations agent, and
 * the three stores the analyst reads sit in the order it reaches them. In a picture whose whole
 * job is "who talks to what", a crossing reads as a wiring mistake.
 */
export type Plane = 'foundry' | 'fabric' | 'semantic' | 'ontology';

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
    label: 'Foundry supervisor',
    detail: 'simulated in this demo',
    plane: 'foundry',
    layer: 0,
    row: 0,
    role: 'Where the service desk agents would call Fabric from. Simulated here: the console asks the data agent directly.',
  },
  {
    id: 'analyst',
    label: 'ServiceDesk_Analyst',
    detail: 'data agent',
    plane: 'fabric',
    layer: 1,
    row: 0,
    role: 'Fabric data agent. Reads the measures, traverses the graph and queries the live stream. Computes no credit itself.',
  },
  {
    id: 'ops',
    label: 'OA_ServiceDesk_Ops',
    detail: 'operations agent',
    plane: 'fabric',
    layer: 1,
    row: 1,
    role: 'Fabric operations agent. Watches the live telemetry and proposes an action when a rule trips.',
  },
  {
    id: 'semantic',
    label: 'SM_ServiceDesk_Analytics',
    detail: '28 measures — every figure',
    plane: 'semantic',
    layer: 2,
    row: 0,
    role: 'Semantic model. The single definition of every figure the console prints, credits included.',
  },
  {
    id: 'ontology',
    label: 'ONT_ServiceDesk',
    detail: '13 entities · XLA clauses',
    plane: 'ontology',
    layer: 2,
    row: 1,
    role: 'Ontology. Answers user - site - incident by traversal, and carries the contractual wording of every XLA.',
  },
  {
    id: 'realtime',
    label: 'EH_ServiceDesk',
    detail: 'live telemetry, 6 tables',
    plane: 'fabric',
    layer: 2,
    row: 2,
    role: 'Eventhouse. Device telemetry, agent traces, gateway logs and surveys as they happen.',
  },
  {
    id: 'lakehouse',
    label: 'LH_ServiceDesk',
    detail: '21 Delta tables',
    plane: 'fabric',
    layer: 3,
    row: 0,
    role: 'Lakehouse. One copy of the data, read in place by the model and the ontology.',
  },
];

export const CHAIN_EDGES: ChainEdge[] = [
  { from: 'supervisor', to: 'analyst', protocol: 'A2A', short: 'simulated' },
  { from: 'analyst', to: 'semantic', protocol: 'DAX' },
  { from: 'analyst', to: 'ontology', protocol: 'GQL' },
  { from: 'analyst', to: 'realtime', protocol: 'KQL' },
  { from: 'ops', to: 'realtime', protocol: 'KQL' },
  { from: 'semantic', to: 'lakehouse', protocol: 'Direct Lake' },
  { from: 'ontology', to: 'lakehouse', protocol: 'Delta' },
];

export const PLANE_LABEL: Record<Plane, string> = {
  foundry: 'Foundry — orchestration (simulated)',
  fabric: 'Fabric — agents, stores',
  semantic: 'Semantic model (DAX)',
  ontology: 'Ontology (GQL)',
};

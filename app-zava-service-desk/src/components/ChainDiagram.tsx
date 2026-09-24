/**
 * The chain, drawn.
 *
 * This component owns pixels and nothing else. Layers, rows and labels come from
 * `@/domain/chain`, so the picture is that declaration rendered rather than a second description
 * of it that can drift out of step.
 *
 * THE GEOMETRY IS HALF OF A CONTRACT
 * ----------------------------------
 *   box 214 wide in a 304 column   -> 90px of clear space for the protocol label
 *   row pitch derived from `tallest` -> boxes in one column never touch
 * SVG text does not wrap and does not clip: it overflows and collides. The `label` and `detail`
 * strings in `chain.ts` are written against exactly these numbers, so moving NW, COL_W or a
 * font-size here means re-checking the longest string there.
 *
 * Ported from the sibling console's `WorkflowDiagram`, minus its status machinery. That version
 * draws a node dashed when a tenant probe failed to find it; here nothing probes anything, so a
 * dashed box would be a distinction the data cannot support.
 */
import { CHAIN_EDGES, CHAIN_NODES, type ChainNode } from '@/domain/chain';

const NW = 214;
const NH = 62;
const COL_W = 304;

/**
 * Plane colour is data, not decoration.
 *
 * Foundry amber against Fabric teal is the one architectural point the picture makes — the data
 * stays on the data side — so the class is derived from `plane` and this component is not free
 * to decide that a box looks Fabric-ish. The hues live in main.css so they follow the theme.
 */
function tone(node: ChainNode): string {
  return `is-${node.plane}`;
}

export function ChainDiagram() {
  const maxLayer = Math.max(...CHAIN_NODES.map((n) => n.layer));
  const perLayer = new Map<number, number>();
  for (const n of CHAIN_NODES) perLayer.set(n.layer, (perLayer.get(n.layer) ?? 0) + 1);
  const tallest = Math.max(...perLayer.values());

  const W = COL_W * (maxLayer + 1);
  const H = Math.max(300, 116 * tallest + 72);

  const pos = new Map<string, { x: number; y: number }>();
  for (const n of CHAIN_NODES) {
    pos.set(n.id, {
      x: COL_W * (n.layer + 0.5),
      y: (H * (n.row + 1)) / ((perLayer.get(n.layer) ?? 1) + 1),
    });
  }

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="wf-svg h-auto w-full"
      role="img"
      aria-label="The deployed chain, from the supervisor down to the lakehouse"
    >
      <defs>
        <marker
          id="chainArrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto"
        >
          <path d="M0,0 L10,5 L0,10 z" className="wf-arrow-head" />
        </marker>
      </defs>

      {CHAIN_EDGES.map((e) => {
        const a = pos.get(e.from);
        const b = pos.get(e.to);
        if (!a || !b) return null;
        const x1 = a.x + NW / 2;
        const x2 = b.x - NW / 2;
        const mx = (x1 + x2) / 2;
        const my = (a.y + b.y) / 2;
        return (
          <g key={`${e.from}-${e.to}`}>
            <path
              d={`M${x1},${a.y} C${x1 + 28},${a.y} ${x2 - 28},${b.y} ${x2},${b.y}`}
              fill="none"
              className="wf-edge"
              strokeWidth={1.5}
              markerEnd="url(#chainArrow)"
            />
            <text
              x={mx}
              y={my - 14}
              textAnchor="middle"
              fontSize="10.5"
              fontWeight="700"
              className="wf-edge-protocol"
            >
              {e.protocol}
            </text>
            {e.short ? (
              <text x={mx} y={my - 3} textAnchor="middle" fontSize="8.5" className="wf-edge-name">
                {e.short}
              </text>
            ) : null}
          </g>
        );
      })}

      {CHAIN_NODES.map((n) => {
        const p = pos.get(n.id)!;
        return (
          <g key={n.id} className={`wf-node ${tone(n)}`}>
            <title>{`${n.label} — ${n.role}`}</title>
            <rect x={p.x - NW / 2} y={p.y - NH / 2} width={NW} height={NH} rx={12} strokeWidth={1.5} />
            <text x={p.x} y={p.y - 3} textAnchor="middle" fontSize="13" fontWeight="700">
              {n.label}
            </text>
            <text x={p.x} y={p.y + 14} textAnchor="middle" fontSize="9.5" opacity="0.85">
              {n.detail}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

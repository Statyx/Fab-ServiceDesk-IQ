import { ChainDiagram } from '@/components/ChainDiagram';
import { Section } from '@/components/Section';
import { CHAIN_NODES, PLANE_LABEL, type Plane } from '@/domain/chain';

/**
 * How the thing is wired, and the one rule that governs it.
 *
 * Second-rank in the nav on purpose: nobody opens a service desk console to read an architecture. It
 * exists for the technical question that lands in the ten minutes after a demo — "what is this
 * actually made of" — and it answers that with a picture, because a numbered list of seven
 * layers is a picture badly drawn.
 *
 * It used to carry a third section listing what the deployment cost us: permission propagation
 * answering 404, a paused capacity answering 404 too, tool approval being per agent. Accurate,
 * hard-won, and none of the customer's business — an app is not the place to prove our own
 * homework. That material belongs in the runbook, not on screen.
 *
 * It is listed in `SECONDARY_NAV`, not `NAV`. For a while it was in neither, which meant the
 * route was reachable only by typing the URL and the page rendered with no heading at all.
 */
const PLANES: Plane[] = ['foundry', 'fabric', 'semantic', 'ontology', 'realtime'];

export function ArchitecturePage() {
  return (
    <>
      <Section
        id="chain"
        title="The chain"
        provenance="Sweden Central — a single region, one copy of the data"
      >
        <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs">
          {PLANES.map((p) => (
            <span key={p} className={`wf-key is-${p}`}>
              {PLANE_LABEL[p]}
            </span>
          ))}
        </div>

        <div className="mt-4">
          <ChainDiagram />
        </div>

        {/* The box holds a label the width allows; the sentence that explains the component
            belongs here, where the browser wraps it properly. */}
        <dl className="mt-4 grid gap-x-6 gap-y-2 sm:grid-cols-2">
          {CHAIN_NODES.map((n) => (
            <div key={n.id} className="grid grid-cols-[auto_1fr] items-baseline gap-2">
              <dt className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>
                {n.label}
              </dt>
              <dd className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                {n.role}
              </dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section id="boundary" title="The boundary rule">
        <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          The semantic model computes, the ontology says what it means, and the data agent does
          neither on its own: it reads the measured value from the model and the clause from the
          graph, and puts the two side by side. The number and the wording both come from Fabric,
          so there is a single place to audit each of them.
        </p>
        <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Practical consequence: no credit is ever recomputed in the console. The model applies
          the contract evaluation, monthly cap included; the app only prints it next to the
          clause that justifies it.
        </p>
        <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Real time has its own path. A question that says "right now" is answered from the
          Eventhouse in KQL, over a window anchored on the latest event, and the answer says it is a
          live window rather than a closed week. The reactive loop does not wait for a question:
          Activator evaluates the VPN telemetry every 60 seconds and alerts Teams, and the operations
          agent watches four goals and proposes the action.
        </p>
        <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Foundry sits on top and keeps the same rule. The supervisor asks the data agent for the
          figures and the contract agent for the clause: the contract agent retrieves it from the
          Foundry IQ knowledge base over the six service agreements, cites it and computes nothing.
          Work IQ adds what is already underway and who owns the next step; Web IQ adds what the
          customer has said in public. None of them produces a figure.
        </p>
      </Section>
    </>
  );
}
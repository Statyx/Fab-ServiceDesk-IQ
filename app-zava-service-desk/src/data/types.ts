/**
 * Types shared across the app.
 *
 * This file used to carry eighteen interfaces describing a telecom estate — sites, cells,
 * interfaces, alarms. Exactly one of them was ever imported here, and a dead type is worse
 * than no type: it invites a future screen to model Zava's domain in a vocabulary Zava's
 * semantic model does not have.
 *
 * Everything else this app displays is a DAX result, and those shapes are declared next to
 * the query that produces them in `data/queries.ts` — so the shape and the DAX it must match
 * are read together, and a renamed column breaks the pair rather than drifting apart.
 */

/**
 * A visual register, not a domain concept.
 *
 * Zava has no incidents to grade. This drives the shared severity palette — the divergent
 * bars on the delivery screen, the failed-probe rows on the diagnostic — so that "this is
 * alarming" is rendered the same way everywhere and is never invented per screen.
 */
export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info';
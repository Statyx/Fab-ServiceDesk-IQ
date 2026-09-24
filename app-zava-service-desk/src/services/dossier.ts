import reference from '@/data/iq-dossier-reference.json';
import webContext from '@/data/iq-web-context.json';
import workContext from '@/data/iq-work-context.json';
import type { DossierInput, WebContext, WorkContext } from '@/domain/dossier';

/**
 * The reviewed scenario, as the page reads it.
 *
 * The figures in the reference file were checked against the live semantic model with the DAX
 * shown under "Figures" on each card. The Work IQ and Web IQ files are fictional and flagged
 * `simulated`: this demo connects no mailbox, no calendar and no web search.
 */
export const DOSSIER_REFERENCE: DossierInput = reference;
export const DOSSIER_WORK_CONTEXT: WorkContext = workContext;
export const DOSSIER_WEB_CONTEXT: WebContext = webContext;

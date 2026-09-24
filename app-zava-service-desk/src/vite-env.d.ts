/// <reference types="vite/client" />

/**
 * Every variable the console reads, declared once so a typo is a build error rather than an
 * `undefined` discovered on stage.
 *
 * All of these are inlined into the bundle at build time and are therefore public. IDs and
 * tenant GUIDs are fine here; a secret never is.
 *
 * Operational screens use the semantic model, never a bundled fallback. The development
 * preview and the explicitly labelled IQ repository walkthrough have their own reference
 * data; neither substitutes it after a failed live request.
 */
interface ImportMetaEnv {
  /** Entra app registration used for the interactive sign-in. */
  readonly VITE_ENTRA_CLIENT_ID?: string;
  readonly VITE_ENTRA_TENANT_ID?: string;

  /**
   * The Power BI semantic model every KPI is read from. Absent, the app renders its
   * structure and no numbers — which is the honest failure, not a broken one.
   */
  readonly VITE_SEMANTIC_MODEL_ID?: string;

  /** Fabric workspace and data agent backing the assistant rail. */
  readonly VITE_ZAVA_WORKSPACE_ID?: string;
  readonly VITE_ZAVA_DATA_AGENT_ID?: string;
  /** Existing ontology-associated Graph Model, for explicit read-only dossier queries. */
  readonly VITE_ZAVA_GRAPH_MODEL_ID?: string;

  /** Rayfin-hosted auth, used when the app runs outside a Fabric item. */
  readonly VITE_RAYFIN_API_URL?: string;
  readonly VITE_RAYFIN_PUBLISHABLE_KEY?: string;

  /** Fabric-hosted auth, used when the app runs as a Fabric item. */
  readonly VITE_FABRIC_WORKSPACE_ID?: string;
  readonly VITE_FABRIC_ITEM_ID?: string;
  readonly VITE_FABRIC_PORTAL_URL?: string;

  /** Dev-server port, assigned per project by Rayfin. */
  readonly VITE_PORT?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
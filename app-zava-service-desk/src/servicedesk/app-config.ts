import { useEffect, useState } from "react";

export interface PortalLink {
    key: string;
    label: string;
    description: string;
    url: string;
}

export interface DemoQuestion {
    source: string;
    question: string;
}

export interface AppConfig {
    workspaceName: string;
    /** The console item in the Fabric portal, where its DAX panels load. Empty before the first deploy. */
    appUrl?: string;
    links: PortalLink[];
    questions: DemoQuestion[];
}

export type AppConfigState =
    | { status: "loading" }
    | { status: "missing" }
    | { status: "ready"; config: AppConfig };

/**
 * `public/app-config.json` is written from config + state by
 * `python -m fabric.app.deploy_app --configure-only` and is git-ignored (portal links
 * carry the workspace and item IDs).
 */
export function useAppConfig(): AppConfigState {
    const [state, setState] = useState<AppConfigState>({ status: "loading" });
    useEffect(() => {
        let cancelled = false;
        fetch(`${import.meta.env.BASE_URL}app-config.json`, { cache: "no-store" })
            .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
            .then((config: AppConfig) => {
                if (!cancelled) setState({ status: "ready", config });
            })
            .catch(() => {
                if (!cancelled) setState({ status: "missing" });
            });
        return () => {
            cancelled = true;
        };
    }, []);
    return state;
}

/** The DAX panels need the Fabric embed proxy, which only exists when Fabric hosts the app in its iframe. */
export function isInsideFabric(win: Window = window): boolean {
    try {
        return win.self !== win.top;
    } catch {
        return true; // cross-origin parent: framed
    }
}

export function groupBySource(questions: DemoQuestion[]): Array<[string, string[]]> {
    const groups = new Map<string, string[]>();
    for (const q of questions) {
        const list = groups.get(q.source) ?? [];
        list.push(q.question);
        groups.set(q.source, list);
    }
    return [...groups.entries()];
}

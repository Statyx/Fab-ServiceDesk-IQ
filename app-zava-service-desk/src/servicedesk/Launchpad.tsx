import { useState } from "react";

import { ArrowUpRightIcon, Card, DashboardGrid, Tile } from "@/components/dashboard";

import { groupBySource, type AppConfigState } from "./app-config";

function CopyButton({ text }: { text: string }) {
    const [copied, setCopied] = useState(false);
    return (
        <button
            type="button"
            className="shrink-0 rounded-md border border-border px-2 py-0.5 font-mono text-[11px] text-muted-foreground transition hover:border-border-strong hover:text-foreground"
            onClick={() => {
                void navigator.clipboard?.writeText(text).then(() => {
                    setCopied(true);
                    setTimeout(() => setCopied(false), 1500);
                });
            }}
        >
            {copied ? "Copied" : "Copy"}
        </button>
    );
}

/**
 * Shown when the console is opened on its hosting URL instead of inside Fabric: the
 * launchpad still works, the DAX panels cannot load.
 */
export function OutsideFabricBanner({ state }: { state: AppConfigState }) {
    const config = state.status === "ready" ? state.config : undefined;
    const target = config?.appUrl || config?.links.find((l) => l.key === "workspace")?.url;
    return (
        <DashboardGrid>
            <Tile size="full">
                <Card eyebrow="Open in Fabric" title="The live numbers load inside Fabric" accent="warning">
                    <p className="text-sm text-muted-foreground">
                        This page is outside the Fabric portal, so the dashboard cannot query
                        SM_ServiceDesk_Analytics. The links and questions below still work.{" "}
                        {target ? (
                            <a href={target} className="font-semibold text-foreground underline underline-offset-2">
                                Open the console in Fabric
                            </a>
                        ) : null}
                    </p>
                </Card>
            </Tile>
        </DashboardGrid>
    );
}

/**
 * Live ops and analyst launchpad. KQL and the Data Agent are not reachable from a
 * Rayfin app (its data SDK only runs DAX), so the real-time and conversational
 * surfaces open in the Fabric portal, next to this console.
 */
export function Launchpad({ state }: { state: AppConfigState }) {
    if (state.status === "loading") return null;
    if (state.status === "missing") {
        return (
            <Card eyebrow="Setup" title="Portal links are not configured" accent="warning">
                <p className="text-sm text-muted-foreground">
                    Run <code className="font-mono">python -m fabric.app.deploy_app --configure-only</code>{" "}
                    from the repository root to write <code className="font-mono">public/app-config.json</code>,
                    then rebuild.
                </p>
            </Card>
        );
    }
    const { links, questions } = state.config;
    return (
        <>
            <DashboardGrid>
                <Tile size="full">
                    <Card
                        eyebrow="Live ops"
                        title="Open the real-time and analyst surfaces"
                        subtitle="They run in the Fabric portal: KQL and the Data Agent are not reachable from an embedded app"
                        accent="chart-2"
                    >
                        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                            {links.map((link) => (
                                <a
                                    key={link.key}
                                    href={link.url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="group flex flex-col gap-1 rounded-lg border border-border bg-surface-1 p-3 transition hover:border-border-strong hover:bg-surface-2"
                                >
                                    <span className="flex items-center justify-between font-display text-sm font-semibold text-foreground">
                                        {link.label}
                                        <ArrowUpRightIcon className="size-4 text-muted-foreground group-hover:text-foreground" />
                                    </span>
                                    <span className="text-xs text-muted-foreground">{link.description}</span>
                                </a>
                            ))}
                        </div>
                    </Card>
                </Tile>
            </DashboardGrid>
            <DashboardGrid>
                {groupBySource(questions).map(([source, list]) => (
                    <Tile key={source} size="md">
                        <Card
                            eyebrow="Ask the Data Agent"
                            title={source}
                            subtitle="Validated at deploy time: paste into ServiceDesk_Analyst"
                        >
                            <ul className="flex flex-col gap-2">
                                {list.map((q) => (
                                    <li key={q} className="flex items-start justify-between gap-3 text-sm text-foreground-secondary">
                                        <span>{q}</span>
                                        <CopyButton text={q} />
                                    </li>
                                ))}
                            </ul>
                        </Card>
                    </Tile>
                ))}
            </DashboardGrid>
        </>
    );
}

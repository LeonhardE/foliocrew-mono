"use client";

import { useCallback, useLayoutEffect, useRef } from "react";
import { isAgentConsentHandoff } from "@/lib/inbox-link";
import { workspaceView, type WorkspaceView } from "@/lib/workspace-routes";

type Journey = "market" | "tasks" | "agents";
type Entry = "document" | "navigation" | "after_unlock";
type Outcome = "ready" | "error" | "timeout" | "access_required" | "interrupted";
type Inputs = {
  view: WorkspaceView;
  access: "available" | "checking" | "blocked" | "error";
  owner: string | null;
  marketState: "loading" | "ready" | "error";
};
type Attempt = { journey: Journey; entry: Entry; start: number };
const measureName = "foliocrew.workspace.journey";
const deadlineMs = 15_000;

function journeyFor(view: WorkspaceView | null): Journey | null {
  if (view === "markets") return "market";
  if (view === "inbox") return "tasks";
  return view === "tasks" || view === "agents" ? view : null;
}

function hasHandoff() {
  return (
    isAgentConsentHandoff(location.search) ||
    /^(#task\/|#inbox\/|#agent_authorization=)/.test(location.hash)
  );
}

function visibleQuote() {
  const quotes = document.querySelectorAll(".market-view:not([hidden]) [data-journey-quote]");
  for (const quote of quotes) {
    const rect = quote.getBoundingClientRect();
    const x = rect.x + rect.width / 2,
      y = rect.y + rect.height / 2;
    if (
      rect.width &&
      rect.height &&
      x >= 0 &&
      y >= 0 &&
      x < window.innerWidth &&
      y < window.innerHeight
    ) {
      const top = document.elementFromPoint(x, y);
      if (top && quote.contains(top)) return true;
    }
  }
  return false;
}

export function createWorkspaceJourneyTracker() {
  let current: Inputs | undefined;
  let active: Attempt | undefined;
  let pending: { view: WorkspaceView; start: number } | undefined;
  let excluded = false;
  let waitingForUnlock = false;
  let frame = 0,
    timer = 0;
  let observer: MutationObserver | undefined;

  function stop() {
    active = undefined;
    observer?.disconnect();
    observer = undefined;
    window.clearTimeout(timer);
    window.cancelAnimationFrame(frame);
    frame = 0;
    window.removeEventListener("scroll", inspect, true);
    window.removeEventListener("resize", inspect);
    document.removeEventListener("transitionend", inspect, true);
    document.removeEventListener("transitioncancel", inspect, true);
  }

  function finish(outcome: Outcome) {
    if (!active) return;
    const { journey, entry, start } = active;
    stop();
    waitingForUnlock = outcome === "access_required";
    try {
      // Keep only the latest entry in the timeline. Observers can consume every completion.
      performance.clearMeasures(measureName);
      performance.measure(measureName, {
        start,
        end: performance.now(),
        detail: { journey, entry, outcome },
      });
    } catch {
      // User Timing is optional. Browser capabilities never gate the workspace.
    }
  }

  function state(): Outcome | null {
    if (!active || !current) return null;
    if (document.visibilityState !== "visible" || hasHandoff()) return "interrupted";
    if (active.journey === "market") {
      if (current.marketState === "ready" && visibleQuote()) return "ready";
      return current.marketState === "error" ? "error" : null;
    }
    if (current.access === "error") return "error";
    if (current.access === "blocked") return "access_required";
    if (current.access === "checking") return null;
    const task = active.journey === "tasks";
    const section = document.querySelector(
      task
        ? '.workspace-page:not([hidden]) [aria-labelledby="task-center-title"]'
        : '.workspace-page:not([hidden]) [data-load-scope="agent-connections"]',
    );
    if (task && section && section.getAttribute("data-load-scope") !== "task-list")
      return "interrupted";
    const loadState = section?.getAttribute("data-load-state");
    return loadState === "ready" || loadState === "error" ? loadState : null;
  }

  function inspect() {
    if (!active || frame) return;
    const result = state();
    if (!result) return;
    // Wait for a paint opportunity, then recheck the same attempt and its committed data.
    const attempt = active;
    frame = window.requestAnimationFrame(() => {
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        if (active === attempt) {
          const final = state();
          if (final) finish(final);
        }
      });
    });
  }

  function begin(journey: Journey | null, entry: Entry, start: number) {
    waitingForUnlock = false;
    if (!journey || excluded || document.visibilityState !== "visible") return;
    active = { journey, entry, start };
    const root = document.getElementById("workspace-content") ?? document.body;
    observer = new MutationObserver(inspect);
    observer.observe(root, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["hidden", "data-load-state", "data-load-scope", "data-journey-quote"],
    });
    if (journey === "market") {
      window.addEventListener("scroll", inspect, true);
      window.addEventListener("resize", inspect);
      // A closing mobile drawer can uncover the quote without changing the quote's DOM.
      document.addEventListener("transitionend", inspect, true);
      document.addEventListener("transitioncancel", inspect, true);
    }
    timer = window.setTimeout(
      () => {
        const result = state();
        finish(result && result !== "ready" ? result : "timeout");
      },
      Math.max(0, deadlineMs - (performance.now() - start)),
    );
    inspect();
  }

  function navigate(view: WorkspaceView | null) {
    if (view !== null && !pending && !excluded && current?.view === view && !hasHandoff()) return;
    finish("interrupted");
    waitingForUnlock = false;
    excluded = view === null;
    pending = view
      ? { view: view === "inbox" ? "tasks" : view, start: performance.now() }
      : undefined;
  }

  function update(next: Inputs) {
    const previous = current;
    current = next;
    if (previous?.owner && previous.owner !== next.owner && active?.journey !== "market") {
      finish("interrupted");
      waitingForUnlock = false;
    }
    if (pending && pending.view !== next.view) return;
    if (!previous || previous.view !== next.view || pending?.view === next.view) {
      finish("interrupted");
      if (hasHandoff()) excluded = true;
      const start = pending?.view === next.view ? pending.start : previous ? performance.now() : 0;
      pending = undefined;
      begin(journeyFor(next.view), previous ? "navigation" : "document", start);
    } else if (!pending && waitingForUnlock && next.access === "available") {
      begin(journeyFor(next.view), "after_unlock", performance.now());
    } else {
      inspect();
    }
  }

  function background() {
    if (document.visibilityState !== "visible") {
      finish("interrupted");
      waitingForUnlock = false;
    }
  }
  function historyChange() {
    navigate(hasHandoff() ? null : workspaceView(location.pathname));
  }
  window.addEventListener("popstate", historyChange);
  window.addEventListener("hashchange", historyChange);
  document.addEventListener("visibilitychange", background);
  return {
    update,
    navigate,
    dispose() {
      stop();
      window.removeEventListener("popstate", historyChange);
      window.removeEventListener("hashchange", historyChange);
      document.removeEventListener("visibilitychange", background);
    },
  };
}

export function useWorkspaceJourney(input: Inputs) {
  const tracker = useRef<ReturnType<typeof createWorkspaceJourneyTracker> | null>(null);
  useLayoutEffect(() => {
    if (
      typeof MutationObserver === "undefined" ||
      typeof window.requestAnimationFrame !== "function" ||
      typeof window.performance?.measure !== "function"
    )
      return;
    const instance = createWorkspaceJourneyTracker();
    tracker.current = instance;
    return () => {
      instance.dispose();
      tracker.current = null;
    };
  }, []);
  useLayoutEffect(() => tracker.current?.update(input));
  return useCallback((view: WorkspaceView | null) => tracker.current?.navigate(view), []);
}

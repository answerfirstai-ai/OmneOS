/** Verification evidence and failure explanations. Primary text stays free of tracebacks. */

import type { VerificationBrief } from "./desktop.js";

export type EvidenceStatus = "PASSED" | "FAILED" | "INCONCLUSIVE" | "NONE";

export interface EvidenceView {
  status: EvidenceStatus;
  lines: string[];
  passedChecks: number;
  totalChecks: number;
}

export interface ErrorView {
  what: string;
  why: string;
  tried: string[];
  next: string;
  technical: string;
}

/** Turn a recorded verification into lines. A missing record is not a pass. */
export function evidenceView(verification: VerificationBrief | null): EvidenceView {
  if (verification === null) {
    return { status: "NONE", lines: [], passedChecks: 0, totalChecks: 0 };
  }
  const lines = [...verification.evidence, ...verification.checks, ...verification.errors];
  const totalChecks = verification.checks.length;
  if (verification.status === "PASS") {
    return { status: "PASSED", lines, passedChecks: totalChecks, totalChecks };
  }
  if (verification.status === "FAIL") {
    const passedChecks = Math.max(0, totalChecks - verification.errors.length);
    return { status: "FAILED", lines, passedChecks, totalChecks };
  }
  if (verification.status === "INCONCLUSIVE") {
    return { status: "INCONCLUSIVE", lines, passedChecks: 0, totalChecks };
  }
  return { status: "NONE", lines, passedChecks: 0, totalChecks: 0 };
}

export function evidenceSummary(views: readonly EvidenceView[]): EvidenceView {
  const recorded = views.filter((view) => view.status !== "NONE");
  if (recorded.length === 0) {
    return { status: "NONE", lines: [], passedChecks: 0, totalChecks: 0 };
  }
  const passedChecks = recorded.reduce((sum, view) => sum + view.passedChecks, 0);
  const totalChecks = recorded.reduce((sum, view) => sum + view.totalChecks, 0);
  const lines = recorded.flatMap((view) => view.lines);
  if (recorded.some((view) => view.status === "FAILED")) {
    return { status: "FAILED", lines, passedChecks, totalChecks };
  }
  if (recorded.every((view) => view.status === "PASSED")) {
    return { status: "PASSED", lines, passedChecks, totalChecks };
  }
  return { status: "INCONCLUSIVE", lines, passedChecks, totalChecks };
}

/** Explain a failure. Tracebacks stay in the technical field. */
export function explainFailure(input: {
  code: string | null;
  message: string;
  decision: string | null;
  alternatives: readonly string[];
}): ErrorView {
  const message = publicMessage(input.message);
  const code = input.code;
  let what = "The mission failed.";
  let next = "Inspect the mission and retry when the cause is resolved.";
  if (code === "denied" || input.decision === "DENY") {
    what = "OMNE denied the request.";
    next = "Change the request so it stays inside the workspace policy.";
  } else if (code === "verification_failed" || message.toLowerCase().includes("verification")) {
    what = "Verification failed.";
    next = "Inspect the evidence and retry the mission.";
  } else if (
    message.toLowerCase().includes("unavailable") ||
    message.toLowerCase().includes("api key")
  ) {
    what = "A required model is unavailable.";
    next = "Configure a model or retry when one is available.";
  }
  const tried =
    input.alternatives.length > 0
      ? [...input.alternatives]
      : input.decision !== null && input.decision !== ""
        ? [input.decision]
        : [];
  return {
    what,
    why: message || "OMNE did not record a reason.",
    tried,
    next,
    technical: technicalText(input.code, input.message),
  };
}

function publicMessage(message: string): string {
  const line = firstLine(message);
  if (line.includes("Traceback") || line.includes('File "')) {
    return "OMNE recorded an internal error.";
  }
  return line;
}

function technicalText(code: string | null, message: string): string {
  const body = message.trim();
  if (body === "") {
    return code ?? "error";
  }
  return code === null || code === "" ? body : `${code}: ${body}`;
}

function firstLine(message: string): string {
  const line = message.split("\n")[0];
  return line === undefined ? "" : line.trim();
}

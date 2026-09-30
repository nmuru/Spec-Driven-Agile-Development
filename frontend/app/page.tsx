
"use client";

import { FormEvent, useEffect, useId, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ReviewCodeBaseControl from "./review-code-base-control";

function MermaidDiagram({ chart }: { chart: string }) {
  const id = useId().replace(/:/g, "");
  const [svg, setSvg] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    async function renderDiagram() {
      try {
        const { default: mermaid } = await import("mermaid");
        mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "default" });
        const cleaned = chart.trim().replace(/^```mermaid\s*/i, "").replace(/```$/i, "").trim();
        const parsed = await mermaid.parse(cleaned);
        if (!parsed) throw new Error("Mermaid could not parse the diagram.");
        const { svg: renderedSvg } = await mermaid.render(`mermaid-${id}`, cleaned);
        if (!cancelled) { setSvg(renderedSvg); setError(""); }
      } catch (err) {
        if (!cancelled) { setSvg(""); setError(err instanceof Error ? err.message : "Unable to render Mermaid diagram."); }
      }
    }
    renderDiagram();
    return () => { cancelled = true; };
  }, [chart, id]);
  if (error) return <div className="mermaid-error"><div>Diagram could not be rendered. Mermaid source is shown below.</div><pre className="markdown-code-block"><code>{chart}</code></pre></div>;
  if (!svg) return <div className="mermaid-loading">Rendering diagram...</div>;
  return <div className="mermaid-diagram" dangerouslySetInnerHTML={{ __html: svg }} />;
}

type Phase = { id: string; label: string; shortLabel: string };
type SpecPhase = { id: string; label: string };
type AnalysisResult = {
  repo_url: string; business_purpose: string; scope: string; business_requirements: string; features: string;
  software_requirements: string; technology_architecture: string; design_pattern: string;
  high_level_design: string; low_level_design: string; implementation_detail: string;
  testing_harness: string; future_directions: string;
};
type Failure = { phase: string; phase_name: string; error_type: string; error: string };
type AnalysisEvent =
  | { type: "phase_completed"; phase: string; phase_name: string; raw_analysis: string; raw_path: string; run_id: string; project_id?: string; sprint_id?: string; provenance?: { model?: string; workflow?: string; project_id?: string; sprint_id?: string } }
  | { type: "analysis_completed"; repo_url: string; run_id: string; completed_phases: string[]; failed_phases?: Failure[] }
  | { type: "analysis_cancelled"; repo_url: string; run_id: string; completed_phases: string[]; failed_phases?: Failure[] }
  | { type: "analysis_failed"; repo_url: string; run_id?: string; error: string };
type RunStatus = { run_id: string; status: string; repo_url: string; selected_phases: string[]; completed_phases: string[]; failures: Failure[]; active_phase: string | null; results: Record<string, string>; project_id?: string; sprint_id?: string };
type StoredWorkspace = { runId: string; repoUrl: string; selectedPhases: string[]; completedPhases: string[]; activePhase: string; status: string; provenance: { model: string } | null; mode: "parallel" | "sequence"; objective: "specify" | "document" | "understand"; intent: string };

const specificationPhases: SpecPhase[] = [
  { id: "scope", label: "Scope" },
  { id: "business-requirements", label: "Business Requirements" },
  { id: "software-requirements", label: "Software Requirements Specification" },
  { id: "design", label: "Design" },
  { id: "tasks", label: "Implementation Tasks" },
  { id: "review", label: "Specification Review" },
];

const phases: Phase[] = [
  { id: "business-purpose", label: "Business Purpose", shortLabel: "Purpose" },
  { id: "scope", label: "Scope", shortLabel: "Scope" },
  { id: "business-requirements", label: "Business Requirements", shortLabel: "Business Requirements" },
  { id: "features", label: "Features", shortLabel: "Features" },
  { id: "software-requirements", label: "Software Requirements", shortLabel: "Software Requirements" },
  { id: "technology-architecture", label: "Technology Architecture", shortLabel: "Architecture" },
  { id: "design-pattern", label: "Design Pattern", shortLabel: "Design Pattern" },
  { id: "high-level-design", label: "High-Level Design", shortLabel: "HLD" },
  { id: "low-level-design", label: "Low-Level Design", shortLabel: "LLD" },
  { id: "implementation-detail", label: "Implementation Detail", shortLabel: "Implementation" },
  { id: "testing-harness", label: "Testing Harness", shortLabel: "Testing" },
  { id: "future-directions", label: "Future Directions", shortLabel: "Future" },
];

const defaultSelectedPhases = ["software-requirements", "technology-architecture", "future-directions"];
const phaseResultMap: Record<Phase["id"], keyof AnalysisResult> = {
  "business-purpose": "business_purpose", scope: "scope", "business-requirements": "business_requirements", features: "features",
  "software-requirements": "software_requirements", "technology-architecture": "technology_architecture",
  "design-pattern": "design_pattern", "high-level-design": "high_level_design", "low-level-design": "low_level_design",
  "implementation-detail": "implementation_detail", "testing-harness": "testing_harness", "future-directions": "future_directions",
};

// const API_BASE_URL = "http://localhost:8000";
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const DEMO_REPO_URL = "https://github.com/vercel/commerce";
const DEMO_RUN_ID = "vercel-demo";
const providers = [
  { id: "openrouter", label: "OpenRouter", placeholder: "e.g. openai/gpt-5, anthropic/claude-sonnet-4" },
  { id: "openai", label: "OpenAI", placeholder: "e.g. gpt-5" },
];

const STORAGE_KEY = "reverse-engineer-sdlc:v1-workspace";

function emptyResult(repoUrl = ""): AnalysisResult {
  return { repo_url: repoUrl, business_purpose: "", scope: "", business_requirements: "", features: "", software_requirements: "", technology_architecture: "", design_pattern: "", high_level_design: "", low_level_design: "", implementation_detail: "", testing_harness: "", future_directions: "" };
}
function makeRunId() { return (typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`).replace(/[^a-zA-Z0-9]/g, ""); }

function SpecifyWorkspace({
  repoUrl,
  loading,
  stopping,
  analysisComplete,
  error,
  specPhases,
  specResults,
  specDrafts,
  specApproved,
  specDirty,
  activePhase,
  setActivePhase,
  setDraft,
  onApprove,
  onClose,
  saving,
  closed,
  onStop,
  runId,
}: {
  repoUrl: string;
  loading: boolean;
  stopping: boolean;
  analysisComplete: boolean;
  error: string;
  specPhases: SpecPhase[];
  specResults: Record<string, string>;
  specDrafts: Record<string, string>;
  specApproved: string[];
  specDirty: Record<string, boolean>;
  activePhase: string;
  setActivePhase: (phase: string) => void;
  setDraft: (phase: string, value: string) => void;
  onApprove: () => void;
  onClose: () => void;
  saving: boolean;
  closed: boolean;
  onStop: () => void;
  runId: string | null;
}) {
  const active = specPhases.find((phase) => phase.id === activePhase) ?? specPhases[0];
  const content = specDrafts[active.id] ?? specResults[active.id] ?? "";
  const completedCount = specPhases.filter((phase) => Boolean(specResults[phase.id])).length;
  const allApproved = specApproved.length === specPhases.length && specPhases.every((phase) => !specDirty[phase.id]);

  return <div className="spec-workspace">
    <aside className="spec-sidebar">
      <div className="sidebar-heading">Sprint Specification</div>
      <div className="progress-label">
        {closed ? "Closed — immutable coding baseline" : loading ? `${completedCount} of ${specPhases.length} phases generated` : analysisComplete ? "All specification phases generated" : "Specification"}
      </div>
      <nav className="phase-nav" aria-label="Specification phases">
        {specPhases.map((phase, index) => {
          const generated = Boolean(specResults[phase.id]);
          const approved = specApproved.includes(phase.id);
          return <button key={phase.id} className={`phase-tab ${activePhase === phase.id ? "active" : ""} ${!generated ? "locked" : ""}`} onClick={() => generated && setActivePhase(phase.id)} disabled={!generated}>
            <span className="phase-number">{String(index + 1).padStart(2, "0")}</span>
            <span className="phase-name">{phase.label}</span>
            <span className={`phase-status ${approved ? "done" : ""}`}>{approved ? "✓" : generated ? "•" : "○"}</span>
          </button>;
        })}
      </nav>
      {!closed && loading && <button type="button" className="spec-stop-button" onClick={onStop} disabled={stopping}>{stopping ? "Stopping..." : "Stop analysis"}</button>}
      {error && <div className="error-banner" role="alert">{error}</div>}
    </aside>

    <main className="content spec-content">
      <section className={`spec-status-banner ${closed ? "closed" : allApproved ? "ready" : ""}`}>
        <div>
          <div className="eyebrow">{closed ? "SPRINT SPECIFICATION CLOSED" : "SPECIFY"}</div>
          <h1>{closed ? "Sprint specification is now immutable." : "Build the specification through progressive review."}</h1>
          <p>{closed ? "This approved specification is the baseline for implementation. It can no longer be edited." : "Each generated phase becomes editable as soon as it arrives. Edit it, then approve it to establish the current canonical version."}</p>
        </div>
        {!closed && <button type="button" className="spec-close-button" onClick={onClose} disabled={!allApproved || saving}>{saving ? "Saving..." : "Close Sprint Specification"}</button>}
      </section>

      <section className="dossier-content">
        <div className="eyebrow">PHASE {String(specPhases.findIndex((phase) => phase.id === active.id) + 1).padStart(2, "0")}</div>
        <h2>{active.label}</h2>
        <p className="section-intro">Repository: {repoUrl.replace(/^https?:\/\//, "")}. {specApproved.includes(active.id) ? "This phase has an approved canonical version." : "Review and edit the generated content before approving it."}</p>
        {content ? <div className="spec-editor-grid">
          <div className="spec-editor-panel">
            <div className="spec-panel-heading">Editable specification</div>
            <textarea value={content} onChange={(event) => setDraft(active.id, event.target.value)} disabled={closed || saving} aria-label={`${active.label} editable specification`} />
            <div className="spec-actions">
              <span>{specApproved.includes(active.id) ? "Approved — approve again after further edits to overwrite the canonical file." : "Not yet approved."}</span>
              {!closed && <button type="button" onClick={onApprove} disabled={saving}>{saving ? "Saving..." : specApproved.includes(active.id) ? "Approve Changes" : "Approve"}</button>}
            </div>
          </div>
          <article className="evidence-card markdown-content spec-preview">
            <div className="spec-panel-heading">Preview</div>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </article>
        </div> : <div className="progress-screen"><div className="spinner"/><div><div className="eyebrow">WAITING FOR SPECIFICATION OUTPUT</div><h1>{loading ? "The next phase is being prepared." : "No specification output is available yet."}</h1><p>The workflow runs sequentially so each phase can use the preceding phase as context.</p></div></div>}
      </section>
    </main>
  </div>;
}

export default function Home() {
  const [repoUrl, setRepoUrl] = useState("");
  const [intent, setIntent] = useState("");
  const [provider, setProvider] = useState("openrouter");
  const [model, setModel] = useState("openrouter/free");
  const [apiKey, setApiKey] = useState("");
  const [mode, setMode] = useState<"parallel" | "sequence">("parallel");
  const [objective, setObjective] = useState<"specify" | "document" | "understand">("specify");
  const [showApiKey, setShowApiKey] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [analysisStarted, setAnalysisStarted] = useState(false);
  const [analysisComplete, setAnalysisComplete] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [activePhase, setActivePhase] = useState("business-purpose");
  const [specActivePhase, setSpecActivePhase] = useState("scope");
  const [specResults, setSpecResults] = useState<Record<string, string>>({});
  const [specDrafts, setSpecDrafts] = useState<Record<string, string>>({});
  const [specApproved, setSpecApproved] = useState<string[]>([]);
  const [specDirty, setSpecDirty] = useState<Record<string, boolean>>({});
  const [specProjectId, setSpecProjectId] = useState<string | null>(null);
  const [specSprintId, setSpecSprintId] = useState<string | null>(null);
  const [specClosed, setSpecClosed] = useState(false);
  const [specSaving, setSpecSaving] = useState(false);
  const [completedPhases, setCompletedPhases] = useState<string[]>([]);
  const [completionMessages, setCompletionMessages] = useState<string[]>([]);
  const [selectedPhases, setSelectedPhases] = useState<string[]>(defaultSelectedPhases);
  const [selectionView, setSelectionView] = useState<"setup" | null>(null);
  const [isDemo, setIsDemo] = useState(true);
  const [loading, setLoading] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [error, setError] = useState("");
  const [failedPhases, setFailedPhases] = useState<string[]>([]);
  const [provenance, setProvenance] = useState<{ model: string } | null>(null);
  const [restored, setRestored] = useState(false);
  const continuationStartingRef = useRef(false);
  const viewedCompletedPhaseRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function restoreWorkspace() {
      try {
        window.localStorage.removeItem(STORAGE_KEY);
        const raw = window.sessionStorage.getItem(STORAGE_KEY);
        if (!raw) { setRestored(true); return; }
        const stored = JSON.parse(raw) as StoredWorkspace;
        if (!stored.runId || stored.runId === DEMO_RUN_ID) { window.sessionStorage.removeItem(STORAGE_KEY); setRestored(true); return; }
        const storedCompleted = stored.completedPhases ?? [];
        const storedSelected = (stored.selectedPhases?.length ? stored.selectedPhases : defaultSelectedPhases).filter((phase) => !storedCompleted.includes(phase));
        setRepoUrl(stored.repoUrl); setIntent(stored.intent ?? ""); setRunId(stored.runId); setSelectedPhases(storedSelected); setMode(stored.mode ?? "parallel"); setObjective(stored.objective ?? "specify");
        setCompletedPhases(storedCompleted); setActivePhase(stored.activePhase || storedCompleted[storedCompleted.length - 1] || storedSelected[0] || phases[0].id);
        setAnalysisStarted(true); setIsDemo(false); setProvenance(stored.provenance ?? null);
        const response = await fetch(`${API_BASE_URL}/api/analysis/${stored.runId}/status`, { cache: "no-store" });
        if (!response.ok) throw new Error("Saved analysis state is no longer available on the backend.");
        const status = await response.json() as RunStatus;
        if (cancelled) return;
        applyStatus(status);
      } catch (err) {
        if (!cancelled) { window.sessionStorage.removeItem(STORAGE_KEY); setError(err instanceof Error ? err.message : "Unable to restore the previous analysis."); }
      } finally { if (!cancelled) setRestored(true); }
    }
    restoreWorkspace();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (objective !== "specify" || !specProjectId || !specSprintId || !analysisStarted) return;
    let cancelled = false;
    async function loadSpecificationState() {
      try {
        const response = await fetch(`${API_BASE_URL}/api/specification/${specProjectId}/${specSprintId}`, { cache: "no-store" });
        if (!response.ok) return;
        const state = await response.json() as { status: string; approved_phases?: string[]; contents?: Record<string, string> };
        if (cancelled) return;
        const contents = state.contents ?? {};
        setSpecResults((previous) => ({ ...previous, ...contents }));
        setSpecDrafts((previous) => ({ ...previous, ...contents }));
        setSpecApproved(state.approved_phases ?? []);
        setSpecDirty({});
        setSpecClosed(state.status === "closed");
      } catch {
        // The streaming run remains the primary source while the backend is working.
      }
    }
    loadSpecificationState();
    return () => { cancelled = true; };
  }, [objective, specProjectId, specSprintId, analysisStarted]);

  useEffect(() => {
    if (!analysisStarted || isDemo || !runId || !restored || analysisComplete || stopped) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/analysis/${runId}/status`, { cache: "no-store" });
        if (!response.ok) return;
        const status = await response.json() as RunStatus;
        if (!cancelled && !continuationStartingRef.current) applyStatus(status);
      } catch { /* SSE is primary during the original request; polling is the refresh fallback. */ }
    };
    poll();
    const timer = window.setInterval(poll, 5000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [analysisStarted, isDemo, runId, restored, analysisComplete, stopped]);

  useEffect(() => {
    if (!analysisStarted || isDemo || !runId) return;
    const snapshot: StoredWorkspace = { runId, repoUrl, intent, selectedPhases, completedPhases, activePhase, status: stopped ? "cancelled" : analysisComplete ? "completed" : stopping ? "cancelling" : "running", provenance, mode, objective };
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
  }, [analysisStarted, isDemo, runId, repoUrl, intent, selectedPhases, completedPhases, activePhase, stopped, analysisComplete, stopping, provenance, mode, objective]);

  function applyStatus(status: RunStatus) {
    const backendCompleted = status.completed_phases ?? [];
    const completed = Array.from(new Set([...completedPhases, ...backendCompleted]));
    const backendSelected = status.selected_phases?.length ? status.selected_phases : defaultSelectedPhases;
    const selected = backendSelected.filter((phase) => !completed.includes(phase));
    const viewedCompletedPhase = viewedCompletedPhaseRef.current;
    const nextActive = viewedCompletedPhase && completed.includes(viewedCompletedPhase) ? viewedCompletedPhase : status.active_phase || selected[0] || activePhase || completed[completed.length - 1] || phases[0].id;
    setRunId(status.run_id); setRepoUrl(status.repo_url); setSelectedPhases(selected);
    setCompletedPhases(completed); setActivePhase(nextActive);
    if (objective === "specify") {
      if (status.project_id) setSpecProjectId(status.project_id);
      if (status.sprint_id) setSpecSprintId(status.sprint_id);
      setSpecResults((previous) => ({ ...previous, ...status.results }));
      setSpecDrafts((previous) => ({ ...previous, ...status.results }));
    }
    setFailedPhases((status.failures ?? []).map((failure) => failure.phase));
    setAnalysisResult((previous) => {
      const next = { ...(previous ?? emptyResult(status.repo_url)), repo_url: status.repo_url };
      for (const [phase, content] of Object.entries(status.results ?? {})) { const key = phaseResultMap[phase as Phase["id"]]; if (key) next[key] = content; }
      return next;
    });
    if (status.status === "completed") { setAnalysisComplete(true); setLoading(false); setStopping(false); setStopped(false); }
    else if (status.status === "cancelled") { setAnalysisComplete(false); setLoading(false); setStopping(false); setStopped(true); }
    else if (status.status === "failed") { setAnalysisComplete(false); setLoading(false); setStopping(false); setError("The analysis could not continue."); }
    else { setAnalysisComplete(false); setLoading(true); if (status.status === "cancelling") setStopping(true); }
  }

  async function loadDemoDocumentation(demoFolder: string, demoRepoUrl: string) {
    try {
      const documents = await Promise.all(phases.map(async (phase) => { const response = await fetch(`/${demoFolder}/${phase.id}.md`); if (!response.ok) throw new Error(`Unable to load demo document: ${phase.id}.md (${response.status})`); return [phase.id, await response.text()] as const; }));
      const result = emptyResult(demoRepoUrl); for (const [phaseId, content] of documents) result[phaseResultMap[phaseId as Phase["id"]]] = content; setAnalysisResult(result);
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to load the Vercel Commerce demo documentation."); }
  }
  //useEffect(() => { if (restored && !window.sessionStorage.getItem(STORAGE_KEY)) loadDemoDocumentation(); }, [restored]);

 /* function viewDemo() {
    if (!analysisResult) return;
    viewedCompletedPhaseRef.current = null;
    setError(""); setRepoUrl(demoRepoUrl); setIntent(""); setRunId(DEMO_RUN_ID); setIsDemo(true); setAnalysisStarted(true); setAnalysisComplete(true); setStopped(false);
    setCompletedPhases(phases.map((phase) => phase.id)); setActivePhase(phases[0].id); setSelectionView(null); setFailedPhases([]); setProvenance(null);
  }*/


  async function viewDemo(demoFolder: string, demoRepoUrl: string) {
  await loadDemoDocumentation(demoFolder, demoRepoUrl);

  viewedCompletedPhaseRef.current = null;
  setError("");
  setRepoUrl(demoRepoUrl);
  setRunId(demoFolder === "vercel-demo" ? "vercel-demo" : "uvdesk-demo");
  setIsDemo(true);
  setAnalysisStarted(true);
  setAnalysisComplete(true);
  setStopped(false);
  setCompletedPhases(phases.map((phase) => phase.id));
  setActivePhase(phases[0].id);
  setSelectionView(null);
  setFailedPhases([]);
  setProvenance(null);
}

  async function analyze(event: FormEvent) {
    event.preventDefault();
    const phasesToRun = objective === "specify" ? specificationPhases.map((phase) => phase.id) : selectedPhases.filter((phase) => !completedPhases.includes(phase));
    if (!provider || !model.trim() || !apiKey.trim()) { setError("Enter an AI provider, model, and API key before starting."); return; }
    if (!repoUrl.trim() || phasesToRun.length === 0) { setError("Enter a repository URL and select at least one new SDLC phase before starting."); return; }
    viewedCompletedPhaseRef.current = null;
    continuationStartingRef.current = Boolean(runId && !isDemo);
    const nextRunId = runId && !isDemo ? runId : makeRunId();
    setRunId(nextRunId); setLoading(true); setStopping(false); setStopped(false); setIsDemo(false); setAnalysisStarted(true); setSelectionView(null); setAnalysisComplete(false); setError(""); setFailedPhases([]);
    setCompletionMessages([]); setActivePhase(phasesToRun[0]);
    setCompletedPhases((previous) => isDemo ? [] : previous);
    setSelectedPhases(phasesToRun);
    setAnalysisResult(isDemo ? emptyResult(repoUrl) : (analysisResult ?? emptyResult(repoUrl)));

    try {
      const response = await fetch(`${API_BASE_URL}/api/analyze`, {
        method: "POST",
        headers: {
          Accept: "text/event-stream",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          repo_url: repoUrl,
          selected_phases: phasesToRun,
          work_id: nextRunId,
          provider,
          model,
          api_key: apiKey,
          mode,
          objective,
          intent: objective === "specify" ? intent : undefined,
        }),
      });

      if (!response.ok) {
        let message = "Analysis failed.";

        try {
          const data = await response.json();

          if (typeof data?.detail === "string") {
            message = data.detail;
          }
        } catch {}

        throw new Error(message);
      }

      if (!response.body) {
        throw new Error("The analysis stream was not available.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();

        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });

        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";

        for (const eventBlock of events) {
          const dataLines = eventBlock
            .split("\n")
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trim());

          if (!dataLines.length) {
            continue;
          }

          let eventData: AnalysisEvent;

          try {
            eventData = JSON.parse(dataLines.join("\n")) as AnalysisEvent;
          } catch {
            continue;
          }

          if (eventData.type === "phase_completed") {
            setRunId(eventData.run_id);

            if (objective === "specify") {
              if (eventData.project_id) setSpecProjectId(eventData.project_id);
              if (eventData.sprint_id) setSpecSprintId(eventData.sprint_id);
              if (eventData.provenance?.project_id) setSpecProjectId(eventData.provenance.project_id);
              if (eventData.provenance?.sprint_id) setSpecSprintId(eventData.provenance.sprint_id);
              setSpecResults((previous) => ({ ...previous, [eventData.phase]: eventData.raw_analysis }));
              setSpecDrafts((previous) => ({ ...previous, [eventData.phase]: eventData.raw_analysis }));
              setCompletedPhases((previous) => previous.includes(eventData.phase) ? previous : [...previous, eventData.phase]);
              setSpecActivePhase(eventData.phase);
              setProvenance({ model: eventData.provenance?.model || model });
              setCompletionMessages((previous) => previous.includes(eventData.phase_name) ? previous : [...previous, `${eventData.phase_name} phase completed`]);
            } else {

            setProvenance(
              eventData.provenance
                ? { model: eventData.provenance.model || model }
                : { model }
            );

            setCompletionMessages((previous) =>
              previous.includes(eventData.phase_name)
                ? previous
                : [...previous, `${eventData.phase_name} phase completed`]
            );

            const resultKey =
              phaseResultMap[eventData.phase as Phase["id"]];

            if (resultKey) {
              setAnalysisResult((previous) => ({
                ...(previous ?? emptyResult(repoUrl)),
                repo_url: repoUrl,
                [resultKey]: eventData.raw_analysis,
              }));

              setCompletedPhases((previous) =>
                previous.includes(eventData.phase)
                  ? previous
                  : [...previous, eventData.phase]
              );

              setSelectedPhases((previous) =>
                previous.filter((id) => id !== eventData.phase)
              );

              setActivePhase(eventData.phase);
            }
            }
          } else if (eventData.type === "analysis_completed") {
            const failures = eventData.failed_phases ?? [];

            setRunId(eventData.run_id);
            setAnalysisComplete(true);
            setLoading(false);
            setStopping(false);
            setStopped(false);
            setFailedPhases(
              failures.map((failure) => failure.phase)
            );

            if (failures.length) {
              setError(
                `${failures.length} selected phase${
                  failures.length === 1 ? "" : "s"
                } could not be completed.`
              );
            }
          } else if (eventData.type === "analysis_cancelled") {
            setRunId(eventData.run_id);
            setAnalysisComplete(false);
            setLoading(false);
            setStopping(false);
            setStopped(true);
            setCompletedPhases(eventData.completed_phases ?? []);
            setFailedPhases(
              (eventData.failed_phases ?? []).map(
                (failure) => failure.phase
              )
            );
            setSelectedPhases((previous) =>
              previous.filter(
                (id) =>
                  !(eventData.completed_phases ?? []).includes(id)
              )
            );
          } else if (eventData.type === "analysis_failed") {
            setError(eventData.error);
            setAnalysisComplete(false);
            setLoading(false);
            setStopping(false);
          }
        }
      }
    } catch (err) {
      if (!stopped) {
        setError(err instanceof Error ? err.message : "Analysis failed.");
        setAnalysisComplete(false);
        setLoading(false);
      }
    } finally {
      continuationStartingRef.current = false;
    }
  }

  async function stopAnalysis() {
    if (!runId || stopping || !loading) return;
    if (!window.confirm("Stop this analysis? No further phases will be started. Completed results will remain available.")) return;
    setStopping(true); setError("");
    try { const response = await fetch(`${API_BASE_URL}/api/analysis/${runId}/stop`, { method: "POST" }); if (!response.ok) throw new Error("The backend did not accept the stop request."); const status = await response.json() as RunStatus; applyStatus(status); }
    catch (err) { setStopping(false); setError(err instanceof Error ? err.message : "Unable to stop the analysis."); }
  }

  async function approveSpecificationPhase() {
    if (!specProjectId || !specSprintId || !specActivePhase || specClosed) return;
    const contentToApprove = specDrafts[specActivePhase] ?? specResults[specActivePhase] ?? "";
    if (!contentToApprove.trim()) return;
    setSpecSaving(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/specification/${specProjectId}/${specSprintId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phase: specActivePhase, content: contentToApprove }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data?.detail || "The specification could not be approved.");
      }
      setSpecResults((previous) => ({ ...previous, [specActivePhase]: contentToApprove }));
      setSpecDirty((previous) => ({ ...previous, [specActivePhase]: false }));
      setSpecApproved((previous) => previous.includes(specActivePhase) ? previous : [...previous, specActivePhase]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to approve the specification.");
    } finally {
      setSpecSaving(false);
    }
  }

  async function closeSpecification() {
    if (!specProjectId || !specSprintId || specClosed) return;
    if (specApproved.length !== specificationPhases.length || specificationPhases.some((phase) => specDirty[phase.id])) {
      setError("Approve every phase, and re-approve any phase changed after its last approval, before closing the sprint specification.");
      return;
    }
    if (!window.confirm("Close this Sprint Specification? The approved specification will become immutable and will be the coding baseline.")) return;
    setSpecSaving(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/specification/${specProjectId}/${specSprintId}/close`, { method: "POST" });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data?.detail || "The sprint specification could not be closed.");
      }
      setSpecClosed(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to close the sprint specification.");
    } finally {
      setSpecSaving(false);
    }
  }

  function resetAnalysis() {
    viewedCompletedPhaseRef.current = null;
    window.sessionStorage.removeItem(STORAGE_KEY); setAnalysisStarted(false); setIsDemo(false); setAnalysisComplete(false); setCompletedPhases([]); setCompletionMessages([]); setRepoUrl(""); setIntent(""); setRunId(null); setProvider("openrouter"); setModel("openrouter/free"); setApiKey(""); setMode("parallel"); setObjective("specify"); setShowApiKey(false); setSelectedPhases(defaultSelectedPhases); setSelectionView(null); setActivePhase(phases[0].id); setAnalysisResult(null); setError(""); setLoading(false); setStopping(false); setStopped(false); setFailedPhases([]); setProvenance(null); setSpecActivePhase("scope"); setSpecResults({}); setSpecDrafts({}); setSpecApproved([]); setSpecDirty({}); setSpecProjectId(null); setSpecSprintId(null); setSpecClosed(false); setSpecSaving(false); continuationStartingRef.current = false;
  }

  const activePhaseDefinition = phases.find((phase) => phase.id === activePhase) ?? phases[0];
  const activeResultKey = phaseResultMap[activePhaseDefinition.id];
  const activeResult = analysisResult && activeResultKey ? analysisResult[activeResultKey] : "";
  const denominator = phases.length;
  const progressText = `${completedPhases.length} of ${denominator} phases have completed. You can read completed phases while the remaining phases continue running.`;

  return <div className="app-shell">
    <header className="topbar"><div><div className="brand">ReverseEngineer-SDLC</div><div className="tagline">Repository → Software Engineering Dossier</div></div>{analysisStarted && repoUrl && <div className="repo-pill" title={repoUrl}>{repoUrl.replace(/^https?:\/\//, "")}</div>}</header>
    {!analysisStarted ? <main className="landing"><div className="landing-card"><div className="eyebrow">AI SOFTWARE REVERSE ENGINEERING</div><h1>Turn a GitHub repository into an SDLC dossier.</h1><p className="landing-copy">Submit a repository URL to progressively reconstruct its business purpose, business requirements, features, software requirements, architecture, design, implementation, testing strategy, and future directions. If you are enhancing an application through a spec-driven development approach, you can use this app to reverse engineer the existing codebase and build specifications that support further development.</p>
      
      

      <div className="demo-links" style={{ marginTop: 20 }}>
        <span>View Samples:</span>
        <button
          type="button"
          className="demo-link"
          onClick={() => viewDemo("vercel-demo", DEMO_REPO_URL)}
          disabled={loading}
        >
          Vercel Commerce Demo
        </button>
        <button
          type="button"
          className="demo-link"
          onClick={() => viewDemo("uvdesk-demo", "https://github.com/uvdesk/community-skeleton")}
          disabled={loading}
        >
          UVdesk Demo
        </button>
      </div>


      <p style={{ marginTop: 20 }}>
        <a
          className="guide-link"
          href="/guide-and-tips.html"
          target="_blank"
          rel="noreferrer"
        >
          ReadMe * Guide & Tips
        </a>
      </p>    




      <fieldset className="phase-selection" style={{ marginTop: 28 }}><legend>AI model</legend><div style={{ display: "grid", gap: 14 }}><label style={{ display: "grid", gap: 7 }}><span style={{ fontSize: 13, fontWeight: 700 }}>Provider</span><select value={provider} onChange={(event) => setProvider(event.target.value)} disabled={loading} aria-label="AI provider" style={{ width: "100%", padding: "12px 13px", border: "1px solid #cfd4da", borderRadius: 9, outline: "none", color: "var(--text)", background: "white" }}>{providers.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label><label style={{ display: "grid", gap: 7 }}><span style={{ fontSize: 13, fontWeight: 700 }}>Model</span><input value={model} onChange={(event) => setModel(event.target.value)} placeholder={providers.find((item) => item.id === provider)?.placeholder} disabled={loading} required aria-label="AI model" autoComplete="off" style={{ width: "100%", padding: "12px 13px", border: "1px solid #cfd4da", borderRadius: 9, outline: "none", color: "var(--text)", background: "white" }} /></label><label style={{ display: "grid", gap: 7 }}><span style={{ fontSize: 13, fontWeight: 700 }}>API key</span><div style={{ display: "flex", gap: 8 }}><input value={apiKey} onChange={(event) => setApiKey(event.target.value)} type={showApiKey ? "text" : "password"} placeholder="Enter your API key" disabled={loading} required aria-label="AI provider API key" autoComplete="off" style={{ minWidth: 0, flex: 1, padding: "12px 13px", border: "1px solid #cfd4da", borderRadius: 9, outline: "none", color: "var(--text)", background: "white" }} /><button type="button" onClick={() => setShowApiKey((value) => !value)} disabled={loading}>{showApiKey ? "Hide" : "Show"}</button></div></label><p style={{ margin: 0, color: "var(--muted)", fontSize: 12 }}>Your API key is used for this analysis request and is not saved by this frontend.</p></div></fieldset>

      <fieldset className="phase-selection" style={{ marginTop: 18 }}><legend>What is your objective?</legend><div style={{ display: "grid", gap: 10 }}><label className="phase-option" style={{ alignItems: "flex-start" }}><input type="radio" name="objective" value="specify" checked={objective === "specify"} onChange={() => setObjective("specify")} disabled={loading} /><span><strong>Specify</strong><br /><span style={{ color: "var(--muted)", fontSize: 12 }}>Turn your intent into a lightweight software specification.</span></span></label><label className="phase-option" style={{ alignItems: "flex-start" }}><input type="radio" name="objective" value="document" checked={objective === "document"} onChange={() => setObjective("document")} disabled={loading} /><span><strong>Document</strong><br /><span style={{ color: "var(--muted)", fontSize: 12 }}>Produce the standard SDLC documentation.</span></span></label><label className="phase-option" style={{ alignItems: "flex-start" }}><input type="radio" name="objective" value="understand" checked={objective === "understand"} onChange={() => setObjective("understand")} disabled={loading} /><span><strong>Understand</strong><br /><span style={{ color: "var(--muted)", fontSize: 12 }}>Explain each completed phase as a clear essay for a developer new to the codebase.</span></span></label></div></fieldset>

      {objective === "specify" && <fieldset className="phase-selection" style={{ marginTop: 18 }}><legend>Intent</legend><label style={{ display: "grid", gap: 7 }}><span style={{ fontSize: 13, fontWeight: 700 }}>What do you want to build or change?</span><textarea value={intent} onChange={(event) => setIntent(event.target.value)} placeholder="Describe what you want to build or change, in your own words. Include the outcome you want, expected behavior, constraints, known technology choices, or anything else that matters." disabled={loading} aria-label="Intent" rows={8} style={{ width: "100%", padding: "12px 13px", border: "1px solid #cfd4da", borderRadius: 9, outline: "none", color: "var(--text)", background: "white", resize: "vertical", font: "inherit", lineHeight: 1.5 }} /></label><p style={{ margin: 0, color: "var(--muted)", fontSize: 12 }}>Intent is the human-authored root artifact. The Specify workflow will progressively turn it into an editable implementation specification.</p></fieldset>}

      {objective !== "specify" && (        <fieldset className="phase-selection" style={{ marginTop: 18 }}><legend>Analysis mode</legend><div style={{ display: "grid", gap: 10 }}><label className="phase-option" style={{ alignItems: "flex-start" }} title="Parallel completes phases faster. Sequential runs phases one after another, allowing later phases to use the results of earlier phases."><input type="radio" name="analysis-mode" value="parallel" checked={mode === "parallel"} onChange={() => setMode("parallel")} disabled={loading} /><span><strong>Parallel</strong><br /><span style={{ color: "var(--muted)", fontSize: 12 }}>Runs phases in parallel.</span></span></label><label className="phase-option" style={{ alignItems: "flex-start" }} title="Parallel completes phases faster. Sequential runs phases one after another, allowing later phases to use the results of earlier phases."><input type="radio" name="analysis-mode" value="sequence" checked={mode === "sequence"} onChange={() => setMode("sequence")} disabled={loading} /><span><strong>Sequential</strong><br /><span style={{ color: "var(--muted)", fontSize: 12 }}>Runs phases one after another; later phases can use earlier phase results.</span></span></label></div></fieldset>
      )}

      <form onSubmit={analyze} className="repo-form"><input value={repoUrl} onChange={(event) => setRepoUrl(event.target.value)} placeholder="https://github.com/owner/repository" type="url" required aria-label="GitHub repository URL" /><button type="submit" disabled={loading}>{loading ? (objective === "specify" ? "Building specification..." : "Reverse engineering...") : (objective === "specify" ? "Start Specify" : "Reverse engineer")}</button></form>
      {objective !== "specify" && (        <fieldset className="phase-selection"><legend>Select SDLC phases</legend><div className="phase-selection-grid">{phases.map((phase) => <label key={phase.id} className="phase-option"><input type="checkbox" checked={selectedPhases.includes(phase.id)} onChange={() => setSelectedPhases((previous) => previous.includes(phase.id) ? previous.filter((id) => id !== phase.id) : [...previous, phase.id])} disabled={loading} /><span>{phase.label}</span></label>)}</div></fieldset>
      )}
      {error && <div className="error-banner" role="alert">{error}</div>}<div className="landing-note">Analysis is performed by the backend coding-agent pipeline.</div>
    </div></main> : objective === "specify" ? <SpecifyWorkspace repoUrl={repoUrl} loading={loading} stopping={stopping} analysisComplete={analysisComplete} error={error} specPhases={specificationPhases} specResults={specResults} specDrafts={specDrafts} specApproved={specApproved} specDirty={specDirty} activePhase={specActivePhase} setActivePhase={setSpecActivePhase} setDraft={(phase, value) => { setSpecDrafts((previous) => ({ ...previous, [phase]: value })); setSpecDirty((previous) => ({ ...previous, [phase]: true })); }} onApprove={approveSpecificationPhase} onClose={closeSpecification} saving={specSaving} closed={specClosed} onStop={stopAnalysis} runId={runId} /> : <div className="workspace">
      <aside className="sidebar"><div className="sidebar-heading">SDLC Dossier</div><div className="progress-label">{loading ? progressText : analysisComplete ? "Analysis complete" : stopped ? `${completedPhases.length} of ${denominator} phases completed before stop` : error ? "Analysis failed" : "Analysis"}</div><nav className="phase-nav" aria-label="SDLC phases"><button className={`phase-tab selection-tab ${selectionView === "setup" ? "active" : ""}`} onClick={() => { viewedCompletedPhaseRef.current = null; setSelectionView("setup"); }}><span className="phase-number">00</span><span className="phase-name">Select Phases</span><span className="phase-status">•</span></button>{phases.map((phase, index) => { const complete = completedPhases.includes(phase.id); return <button key={phase.id} className={`phase-tab ${activePhase === phase.id ? "active" : ""} ${!complete ? "locked" : ""}`} onClick={() => { if (complete) { viewedCompletedPhaseRef.current = phase.id; setSelectionView(null); setActivePhase(phase.id); } }} disabled={!complete}><span className="phase-number">{String(index + 1).padStart(2, "0")}</span><span className="phase-name">{phase.label}</span><span className={`phase-status ${complete ? "done" : ""}`}>{complete ? "✓" : "•"}</span></button>; })}</nav><ReviewCodeBaseControl repoUrl={repoUrl} provider={provider} model={model} apiKey={apiKey} runId={runId} completedPhases={completedPhases} />{runId && !isDemo && completedPhases.length > 0 && <a className="download-button" href={`${API_BASE_URL}/api/analysis/${runId}/download`} download="sdlc-documentation.zip">Download completed work</a>}<button className="new-analysis" onClick={resetAnalysis} disabled={loading || stopping}>+ New repository</button></aside>
      <main className="content">
        {selectionView === "setup" ? <section className="selection-panel"><div className="eyebrow">ANALYSIS SETUP</div><h1>Continue analysis</h1><p className="section-intro">Select additional SDLC phases to run in this repository workspace. Completed phases remain readable here and are not rerunnable in V1. To rerun a completed phase, open a new browser tab/workspace.</p><fieldset className="phase-selection"><legend>Run phases</legend><div className="phase-selection-grid">{phases.map((phase) => { const complete = completedPhases.includes(phase.id); return <label key={phase.id} className="phase-option"><input type="checkbox" checked={!complete && selectedPhases.includes(phase.id)} onChange={() => setSelectedPhases((previous) => previous.includes(phase.id) ? previous.filter((id) => id !== phase.id) : [...previous, phase.id])} disabled={loading || stopping || complete} /><span>{phase.label}{complete ? " (completed)" : ""}</span></label>; })}</div></fieldset><form onSubmit={analyze} className="repo-form"><input value={repoUrl} onChange={(event) => setRepoUrl(event.target.value)} placeholder="https://github.com/owner/repository" type="url" required aria-label="GitHub repository URL" disabled={true} readOnly /><button type="submit" disabled={loading || stopping}>{loading ? "Running..." : "Run selected phases"}</button></form>{error && <div className="error-banner" role="alert">{error}</div>}</section>
        : isDemo ? <><section className="completion-banner"><div><div className="eyebrow">EXAMPLE DOCUMENTATION</div><h1>{repoUrl.includes("uvdesk") ? "UVdesk software dossier" : "Vercel Commerce software dossier"}</h1><p>Browse the pre-generated twelve-phase reverse-engineering documentation.</p></div><div className="completion-mark">✓</div></section><section className="dossier-content"><div className="eyebrow">STAGE {String(phases.findIndex((phase) => phase.id === activePhase) + 1).padStart(2, "0")}</div><h2>{activePhaseDefinition.label}</h2><p className="section-intro">Pre-generated reverse-engineering documentation for the {repoUrl.includes("uvdesk") ? "UVdesk" : "Vercel Commerce"} repository.</p><article className="evidence-card markdown-content">{activeResult ? <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ code({ className, children, ...props }) { if (/language-mermaid/.test(className || "")) return <MermaidDiagram chart={String(children).replace(/\n$/, "")} />; return <code className={className} {...props}>{children}</code>; } }}>{activeResult}</ReactMarkdown> : <div className="mermaid-loading">Loading demo documentation...</div>}</article></section></>
        : <>{loading && <section className="progress-screen"><div className="spinner"/><div><div className="eyebrow">ANALYSIS IN PROGRESS</div><h1>Results are arriving progressively</h1><p>{progressText}</p>{stopping ? <p style={{ fontWeight: 700 }}>Stop requested. Waiting for the current backend work to unwind safely.</p> : <button type="button" onClick={stopAnalysis} disabled={stopping} style={{ minHeight: 42, padding: "0 16px", border: "1px solid #b42318", borderRadius: 8, background: "white", color: "#b42318", fontWeight: 700 }}>{stopping ? "Stopping analysis..." : "Stop analysis"}</button>}{completionMessages.length > 0 && <div className="completion-messages" aria-live="polite">{completionMessages.map((message) => <div key={message}>{message}</div>)}</div>}</div></section>}
          {stopped && <section className="completion-banner" style={{ borderColor: "#ead9c5", background: "#fffaf3" }}><div><div className="eyebrow">ANALYSIS STOPPED</div><h1>The analysis was stopped by the user.</h1><p>{completedPhases.length} of {denominator} phases completed before stop.</p><button type="button" onClick={resetAnalysis} style={{ marginTop: 14, minHeight: 42, padding: "0 16px", border: 0, borderRadius: 8, background: "var(--accent)", color: "white", fontWeight: 700 }}>Back to Main Page</button></div></section>}
          {analysisComplete && <section className="completion-banner"><div><div className="eyebrow">REVERSE ENGINEERING COMPLETE</div><h1>Your software dossier is ready.</h1><p>Visit the individual SDLC tabs on the left to explore the SDLC Dosier.</p></div><div className="completion-mark">✓</div>{runId && <a className="download-button" href={`${API_BASE_URL}/api/analysis/${runId}/download`} download="sdlc-documentation.zip">Download ZIP</a>}</section>}
          {activeResult && <section className="dossier-content"><div className="eyebrow">STAGE {String(phases.findIndex((phase) => phase.id === activePhase) + 1).padStart(2, "0")}</div><h2>{activePhaseDefinition.label}</h2><p className="section-intro">Analysis returned by the backend coding-agent pipeline for this SDLC phase.{provenance ? ` Model: ${provenance.model}` : ""}</p><article className="evidence-card markdown-content"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ code({ className, children, ...props }) { if (/language-mermaid/.test(className || "")) return <MermaidDiagram chart={String(children).replace(/\n$/, "")} />; return <code className={className} {...props}>{children}</code>; } }}>{activeResult}</ReactMarkdown></article></section>}
          {!loading && !stopped && !analysisComplete && !activeResult && error && <section className="progress-screen"><div><div className="eyebrow">ANALYSIS FAILED</div><h1>The analysis could not continue.</h1><p>{error}</p></div></section>}
        </>}
      </main>
    </div>}
  </div>;
}

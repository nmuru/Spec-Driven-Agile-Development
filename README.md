# Spec-Driven Agile Development

An AI-assisted workflow for turning development intent into concise, reviewable specifications that can guide coding agents during an Agile sprint.

This project explores a practical question: how can the speed of AI coding be combined with the discipline of software specification without recreating the long feedback cycles of traditional waterfall development?

## What is Spec-Driven Agile Development?

Spec-Driven Development (SDD) makes the specification a primary working artifact for implementation.

Instead of asking an AI coding agent to move directly from an idea to code, the human first states the development intent. The application progressively elaborates that intent into a small set of implementation-oriented specifications. The human reviews, edits and approves each stage before the next stage is generated.

The resulting specification is not intended to be a large piece of permanent documentation. It is a concise working contract between the development team and the coding agent.

The basic loop is:

**Human Intent → Scope → Requirements → Technology → Design → Implementation Tasks → Coding Agent**

The human remains responsible for intent, decisions and approval; AI does the bulk of the specification elaboration and can subsequently use the approved specification to implement the work.

## Why connect SDD with Agile?

SDD does not replace Agile or Scrum. They address different levels of the development process.

The Product Backlog carries product intent, priorities and context. The Sprint Backlog selects the work to be undertaken. Detailed specification belongs closer to execution, when the team is actually ready to build something.

This application therefore treats a sprint Intent as the starting point for specification. A developer, pair, small group, or swarm can take the selected work and progressively clarify it with AI before implementation begins.

This separation also avoids duplicating capabilities already provided by Agile project-management tools such as Jira. Those tools can remain responsible for backlog, sprint and delivery management, while this application focuses on the technical elaboration required immediately before coding.

## The Specify workflow

The Specify option is a human-gated, progressive workflow:

1. **Intent** — The technical team describes the development goal, desired outcome, boundaries, constraints and known technology decisions.
2. **Scope** — Establish what belongs in the current sprint and what is explicitly outside it.
3. **Business Requirements** — Develop a concise working interpretation of the business need from the Intent, product context and available evidence.
4. **Software Requirements** — Translate the approved scope and requirements into implementation-oriented software behaviour.
5. **Technology Architecture** — Identify how the requested change fits the existing product technology and architecture.
6. **Design** — Establish the relevant implementation design within the existing system.
7. **Implementation Tasks** — Break the approved design into concrete, AI-sized tasks suitable for the current sprint.

Each phase is generated only after the previous phase is approved. The user can edit the generated content before approval. A failed phase can be retried without discarding previously approved phases.

The specification is stored as sprint-level Markdown artifacts under:

`<Project Folder>/<Product Name>/spec_output/sprint-N/`

The product folder must already exist and contain a human-maintained `project.md`, which provides product-level context.

## Sprint model

A Specify run represents one development sprint specification.

New Sprint creates the next numbered sprint folder:

- `sprint-1`
- `sprint-2`
- `sprint-3`
- ...

Existing Sprint can reuse the latest active sprint when a specification needs to be restarted or revised. A closed sprint specification is treated as the implementation baseline and is no longer editable.

The workflow is intentionally sprint-bounded. If the Intent represents work that is too large for the current sprint, the specification should expose that scope rather than silently turning it into a multi-week implementation.

## Repository context

A GitHub repository URL is optional for Specify.

When supplied, the existing repository provides technical evidence for the specification. The agents can inspect the codebase and distinguish existing implementation from proposed changes. Explicit human Intent remains the primary input; repository evidence should not silently override it.

This makes the workflow useful both for new development and for enhancing an existing application.

## Specify and Document are complementary

The application also retains its original **Document** capability.

The two workflows serve different purposes:

- **Specify** creates concise, sprint-level, coding-agent-ready specifications for work about to be implemented.
- **Document** reverse engineers a repository into a broader SDLC dossier covering areas such as business purpose, scope, requirements, architecture, design, implementation, testing strategy and future directions.

This makes the same product useful throughout the development lifecycle. Once a project has a GitHub repository, the repository can provide technical context for Specify and can also be analysed through Document to create or refresh the wider SDLC dossier.

## Human in the loop

The application deliberately does not give the specification agent unrestricted authority over the project files.

Specification agents are read-only during generation. They return the proposed specification to the application; the application persists the approved artifact.

This keeps an explicit boundary between:

- human-authored Intent,
- AI-generated interpretation,
- human approval,
- and subsequent implementation by a coding agent.

The goal is not to eliminate human engineering judgment, but to move that judgment to the points where it has the greatest leverage.

## AI providers

The current version supports the providers routed by the backend:

- OpenRouter
- OpenAI

The selected model is supplied with the request. There is no silent model fallback: provider, authentication, rate-limit and model failures are surfaced to the user.

API keys are entered for the analysis request and are not stored by the frontend.

## Local development

Clone the repository:

```bat
git clone https://github.com/nmuru/Spec-Driven-Agile-Development.git
cd Spec-Driven-Agile-Development
```

Requirements:

- Git
- Python 3.11+
- Node.js 20.9+
- An API key for the selected AI provider

On Windows, the repository includes `start.bat` for running the application. If its environment-specific paths do not match your machine, run the services manually.

Backend:

```bat
cd backend
python -m venv .venv
.venv\\Scripts\\python.exe -m pip install -r requirements.txt
.venv\\Scripts\\python.exe -m uvicorn app.main:app --reload
```

Frontend, in a second terminal:

```bat
cd frontend
npm install
npm run dev
```

The frontend normally runs at `http://localhost:3000` and the backend at `http://localhost:8000`.

## Using Specify locally

Before starting a Specify run, provide:

- **Product Name** — the product directory name.
- **Project Folder** — the parent folder containing the product directory.
- **project.md** — a human-maintained product context file inside the product directory.
- **Intent** — the work you want to specify for the sprint.
- **Provider, model and API key**.
- **GitHub repository URL**, when an existing repository should provide technical evidence.

For a new sprint, select **New Sprint**. To restart the latest active sprint, select **Existing Sprint**.

After the phases are approved, use **Close Sprint Specification** to establish the specification as the sprint's implementation baseline.

## Example

For example, an ecommerce product might begin a sprint with an Intent such as:

> Build the first usable storefront experience where a customer can discover products, browse the catalog, search and filter products, view product details and understand available product options.

The application can then progressively turn that Intent into scope, requirements, architecture, design and implementation tasks rather than asking a coding agent to infer all of those decisions directly from a short prompt.

## Project structure

The important product-level structure is:

```text
<Project Folder>/
  <Product Name>/
    project.md
    spec_output/
      sprint-1/
        sprint-state.json
        intent.md
        scope.md
        business-requirements.md
        software-requirements.md
        technology.md
        design.md
        tasks.md
      sprint-2/
        ...
      repository/
        document/
          ... Document-mode SDLC outputs ...
```

The sprint specification artifacts are intended to remain small, readable and directly useful to implementation.

## Current status

This repository is a working exploration of Spec-Driven Agile Development rather than a claim of a finished methodology or production-hardened platform.

The core workflow is intentionally frozen at a usable V1 milestone. Further edge-case testing, integrations and workflow refinements can be added in subsequent iterations.

## License

See the repository for the applicable license and project files.

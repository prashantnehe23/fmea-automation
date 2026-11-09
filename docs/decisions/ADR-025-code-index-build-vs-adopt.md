# ADR-025: Code Index — Build a Thin Tree-sitter Index, Do Not Embed Graphify or CodeGraph

**Status:** Accepted (default approved by the engineer 2026-11-09: "build thin on tree-sitter unless the spike says otherwise"; the spike did not say otherwise)  **Date:** 2026-11-09  **Backlog:** B-036 (phase 0 spike)

## Context
The exploit verifier (ADR-015 and its addendum 2) must trace entry point -> data flow -> sink, so it needs symbols, callers and callees, entry points and sinks. Today only `read_file` and a substring `search_code` exist, and nothing understands Java, C# or TypeScript. The question was whether to adopt an existing code-graph tool (Graphify, CodeGraph) or build a thin index on tree-sitter.

## Spike method
Four small labelled repositories with the same shape (two HTTP entry points, one `main`, a controller -> service -> repository chain with three SQL sinks, one file sink and one command sink): Python/FastAPI, Java/Spring, C#/ASP.NET, TypeScript/Express (`benchmarks/index_repos/`, truth generated from anchors by `make_truth.py`, 7 labelled call edges, 3 entry points, 5 sinks each). One common output shape and scorer (`benchmarks/index_spike/`). Candidates ran in isolated environments on copies of the repositories, with telemetry off and any proxied network traffic pointed at a dead port. Nothing was installed into the project's own environment, and neither tool's agent/IDE installer was run.

## Results
| Candidate | Call recall (Py / Java / C# / TS) | Call precision | Entry points | Sinks | Index time (4-5 files) |
|---|---|---|---|---|---|
| **In-house tree-sitter prototype** | 1.00 / 1.00 / 1.00 / 1.00 | 0.88 / 1.00 / 1.00 / 0.78 | 1.00 on all four | 1.00 on all four | under 0.05 s |
| **Graphify** (`graphifyy` 0.9.105, offline `graphify update`) | 0.71 / 1.00 / 1.00 / 0.71 | 1.00 on all four | not provided | not provided | about 0.8 s cold |
| Graphify, only edges tagged EXTRACTED | 0.14 on all four | 1.00 | not provided | not provided | |
| **CodeGraph** (`@colbymchenry/codegraph` 1.6.2) | 0.43 / 0.71 / 0.71 / 0.86 | 1.00 on all four | 0.00 / 0.67 / 0.67 / 0.67 (routes only; no `main`) | not provided | 0.4-1.5 s |

Entry-point idiom probe (eight common framework idioms, one tiny file each): in-house detects 5 of 8 (misses Django `urlpatterns`, ASP.NET minimal-API `MapGet`, JAX-RS `@Path/@GET`); CodeGraph detects 1 of 8 (Spring `@RequestMapping`). Graphify was not probed: it emits no entry points.

Honest limits of these numbers: the fixtures are tiny and were written by the same engineer (me) who wrote the in-house rules, so the in-house entry-point and sink scores of 1.00 show the rules cover the fixtures, not that they generalise; the idiom probe is the better indicator of the gap. Speed on a 300 KB repository was not measured.

## Findings that drive the decision
1. **Neither tool detects sinks, and entry-point coverage is thin** (Graphify none, CodeGraph a few frameworks). We need our own detectors regardless, and they have to look at call expressions in the syntax tree, so we need a parser in-process anyway.
2. **Callee resolution is where they beat us.** Both resolve a call to the callee's definition and file (precision 1.00); our name-based edges conflate same-named methods (`@router.get(...)` and `db.prepare(...).get(x)` become calls to `OrderRepository.get`: 0.88 and 0.78). Receiver-aware resolution is therefore the main piece of work in phase 1, not parsing.
3. **Call recall on chained receivers.** Graphify loses `new X().m()` style calls (Python/TS 0.71); CodeGraph loses more. The in-house index records them.
4. **Graphify's cross-file method edges are tagged INFERRED** (recall 0.14 without them), i.e. produced by heuristics, not certain syntax.
5. **Supply-chain and operational footprint.** Graphify: PyPI metadata has no author, an installer that rewrites agent configuration, instruction files and hooks (not run), dozens of dependencies (networkx, numpy, about two dozen grammar packages), and conflicting accounts of its maintainer across sources. CodeGraph: ships a 92 MB bundled `node.exe` plus a native kernel per platform from a single maintainer (npm signatures and provenance attestations did verify; no install scripts), default telemetry setting not stated, an installer that writes MCP configuration. Both are young and fast-moving. The hostile-repository threat model (ADR-017/021) argues against adding opaque native components or an optional LLM pass to the scan path.
6. **`tree-sitter-language-pack` 1.x exposes a download manager** (grammars fetched on demand), so it is not used. The official per-language wheels (`tree-sitter-python`, `-java`, `-c-sharp`, `-typescript`, `-javascript`, MIT, static grammars) worked offline.

## Decision
1. **Build a thin in-house index** (`core/code_index.py`, promoted from `benchmarks/index_spike/inhouse.py`) on `tree-sitter` with the official per-language wheels, pinned in `requirements.txt`; Python additionally may use the standard `ast` module where it gives better resolution.
2. **Receiver-aware call resolution** (class fields, constructor assignments, `new X().m()` chains, imports) is the first piece of phase 1; the target is call precision of 1.00 on the fixtures without losing recall.
3. **Entry-point and sink detectors are data-driven** (framework rule tables) so a framework is a table entry; the missing idioms from the probe (Django, ASP.NET minimal APIs, JAX-RS, route prefixes) are phase 2 items.
4. **Graphify and CodeGraph are not embedded.** They remain usable as optional, user-run comparators or a future "bring your own index" import, but nothing in the scan path may depend on them.
5. Every language the index cannot handle falls back to text tools and is marked `confidence: low` (B-036 scope).

## Alternatives considered
- Adopt Graphify as the graph layer: best resolved call edges for Java/C#, but no entry points or sinks, heavy dependencies, an installer that modifies agent configuration, and reliance on heuristic INFERRED edges.
- Adopt CodeGraph: verified npm provenance and a queryable SQLite index, but weakest recall here, few route idioms, a bundled runtime binary and unclear telemetry default.
- Data-flow engines (Joern, CodeQL, SCIP indexers): not evaluated in this spike. CodeQL's licence needs checking for SaaS use and SCIP indexers for Java/C# compile the project (executing untrusted build steps). Joern remains a candidate for a later taint-analysis step.
- A pure LLM approach (the model reads files and guesses callers): what exists now; unreliable at scale and the thing B-036 replaces.

## Consequences
- We own a parser-based component and must keep its framework tables current; the idiom probe and the fixtures are the regression net.
- New runtime dependencies (tree-sitter and four or five grammar wheels) arrive with phase 1; they are small, MIT-licensed and have prebuilt Windows wheels.
- If receiver-aware resolution proves harder than expected for Java or C# (type inference through generics and dependency injection), importing a candidate's resolved edges as an optional source stays open.
- The spike repositories can be extended with vulnerability labels for the language-coverage work (B-039) without further authoring.

## Implementation notes (phase 1, 2026-11-09)
- The prototype became `core/code_index.py`; it works on `{path: text}` only (no file system), so it indexes a stored scan snapshot exactly as the chat sees it.
- Receiver-aware resolution lifted call precision on the spike repositories from 0.78-0.88 to 1.00 with recall unchanged. The key rule is that a receiver whose type is not defined in the scanned code (a framework, driver or `express()` result) creates no edge, which removes `@router.get(...)` and `db.prepare(...).get(x)` being read as calls to a repo method named `get`.
- Index build time: 0.25 s for 307 KB in 630 files across the four languages.
- `tree-sitter-javascript` is not pinned: plain JavaScript is parsed with the TypeScript grammar.

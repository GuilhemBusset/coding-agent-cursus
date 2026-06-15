## Session 1 — Fundamentals
- Token & tokenization (BPE / sub-word units; the model sees integer IDs, not characters) — the structural cause of the strawberry/blueberry letter-count failure
- Next-token prediction as a learned conditional distribution p(x_t | x_<t); autoregression as a sequence-joint factorization
- Sampling and temperature as a one-parameter reshaping of the output distribution (T->0 near-greedy/deterministic; the root of non-reproducibility)
- Attention as a soft, differentiable database lookup: output = expectation of value vectors under a query-dependent softmax measure; permutation-equivariance; multi-head = parallel lookups (intuition only)
- Context window as a finite token buffer; the model as a PURE FUNCTION of its current context (no memory between calls; the 'conversation' is an illusion the harness maintains by re-feeding the transcript)
- KV cache as memoization of already-processed prefixes (cost/latency intuition)
- Hallucination as a structural consequence (no truth oracle, no reserved 'I don't know' mass) -> OR stakes: a confident wrong constraint / flipped objective sense reads as fluently as a correct one
- Perceive-plan-act-observe agent loop (Russell & Norvig 1995; ReAct, Yao et al. 2022); 'the loop keeps the model honest'
- Agent = Model + Harness ('if you're not the model, you're the harness'); tools, system prompt, filesystem, while-loop, stop conditions
- Stop conditions and their two failure modes (runaway loop vs. premature 'done' while tests are red); chatbot (single forward pass) vs. agent (bounded loop corrected by reality)
- Reliability-controls taxonomy recap (boundary / context / contract / verification / traceability) mapped onto the live demos and this repo's guard-main.sh and pr-only.yml
- Deliberate CUTS: backprop, gradient descent, training loss, transformer block internals, RLHF, scaling laws, all benchmark numbers

## Session 2 — Research Agents (skills & sub-agents that produce a document)
- Two anchor case studies, both OPEN, inspectable, and built on the Skill primitive (introduced fresh in this cursus, not assumed), both uv-managed: Ar9av/PaperOrchestra and google-deepmind/science-skills
- PaperOrchestra (impl. of Song et al., arXiv:2604.05018): a multi-agent pipeline turning (idea.md + experimental_log.md + template.tex + conference_guidelines) into a submission-ready LaTeX paper — Outline -> (Plotting || Literature-Review, parallel branches) -> Section-Writing (one multimodal call) -> Content-Refinement (accept/revert peer-review loop with halt rules)
- Skills-as-instruction-docs-plus-deterministic-scripts: SKILL.md (+ references/ verbatim prompts, JSON schemas) + scripts/ (no network, no LLM, no API keys); the host coding agent supplies the model + web search
- THE central design lesson = the cursus thesis as software: a hard split between DELEGATED judgment (write/search/decide -> host LLM) and DETERMINISTIC gates (Levenshtein title-match vs Semantic Scholar, date-cutoff, dedup, >=90% citation-integration, orphan-cite gate, anti-leakage grep, Citation-F1) -> 'put the citation gate in code the model cannot talk past'
- Autoraters as LLM-as-judge wired into a real pipeline (Citation F1 P0/P1, 6-axis LitReview quality, SxS quality) — callback to the workshop's LLM-judge
- agent-research-aggregator: scans your own .claude/.cursor agent logs and synthesizes idea.md + experimental_log.md -> agent logs are auditable research provenance
- Refinement loop semantics: physical snapshots + score-delta accept/revert + halt rules; provenance hashes of inputs/outputs (reproducibility, out-of-paper hardening)
- google-deepmind/science-skills (Apache-2.0): GROUNDING via skills wrapping real APIs/tools — UniProt/AlphaFold/ChEMBL/ClinVar/Ensembl/GTEx databases, PyMOL/Foldseek, and literature search (OpenAlex / EuropePMC / arXiv); workflow_skill_creator (a skill that writes skills); uv-managed
- Composition (PaperOrchestra) vs grounding (science-skills) as the two halves of a research agent; the OR analog = an unfilled opportunity to build a math.OC skill pack
- The commercial 'deep research' category in brief (Gemini Deep Research / OpenAI / Perplexity): background async run, quality scales with test-time compute, anytime search + stopping rule — taught only as context, explicitly NOT trusted on faith
- Provenance hygiene as a live lesson: neither anchor is 'from a Chinese lab' (science-skills = Google DeepMind; PaperOrchestra implements a Google-authored paper) — check a claim's source before repeating it
- Failure modes taught FIRST, with sourced numbers students re-derive from the reading list: invented citations; over-retrieval lowering accuracy; ~40-80% citation/factual accuracy even when links resolve; ~one-fifth foundational-canon recall; one-sidedness/majority bias
- Claim-level auditability as the design + evaluation target (check synthesized claims, not just sourced ones); 'drive then AUDIT'
- Lab discipline: run PaperOrchestra on a real P-pack/prior-workshop study, audit the draft (citation-validity, fabrication rate, foundational-recall vs an instructor gold list), and author ONE OR research skill (arXiv math.OC search or a MILP instance library) as a boundary control that lowers fabrication

## Session 3 — Types of Coding Agents (Local -> Remote)
- Local agentic harnesses: Claude Code CLI, OpenAI Codex CLI, Gemini CLI (Apache-2.0, ReAct + MCP), aider — actions on the local filesystem with confirmation prompts; you are in the loop synchronously
- Headless / programmatic mode as the Rosetta Stone: claude -p print mode; --output-format text|json|stream-json; session resume, --max-turns, --allowedTools, --dangerously-skip-permissions (CI-only); stream-json as a mid-run kill switch (SIGINT)
- Claude Agent SDK: query(), typed messages, tool-approval callbacks, JSON-Schema structured outputs; the SDK/Action are headless mode wrapped in plumbing ('remote' = packaging, not magic)
- anthropics/claude-code-action (the remote face of Claude Code): @claude trigger, runs the full runtime inside your own GitHub runner; Anthropic hosted progression — Remote Control -> Remote Tasks -> Routines (laptop off) -> Managed Agents (harness + secure sandbox)
- The ephemeral cloud sandbox model: issue/prompt -> token-scoped repo clone -> network-isolated disposable microVM (Firecracker/gVisor/Kata) -> tests/linters -> draft PR -> teardown
- Brain/hands separation: stateless secret-free sandbox + stateful control-plane holding credentials & conversation state = safely scalable parallel agent FLEETS
- Remote platform contrast: Codex cloud (network-isolated; internet + secrets stripped during agent phase), GitHub Copilot coding agent (GA, draft PR, PRs need approval before CI/CD), Google Jules (GCloud VMs, strong free tier), Cursor background agents, Devin (per-ACU billing)
- MCP (vertical, agent->tools/data/memory) vs A2A/Agent2Agent (horizontal, agent->agent discovery/delegation/coordination); Linux Foundation governance, 150+ orgs; pattern: 'build with framework, equip with MCP, communicate with A2A'
- Agent-mesh / swarm orchestration over A2A+MCP — taught as a PATTERN, demonstrated with REAL inspectable frameworks (LangGraph, CrewAI, AutoGen, reference A2A SDKs), explicitly avoiding unverifiable marketing 'swarm runtime' product names
- Fleet governance: non-human identity (scoped, revocable per-agent credentials), least-privilege that travels across delegation, inter-agent observability/audit
- Egress controls: deny-by-default + allowlist, block 169.254.169.254 (cloud IMDS) and RFC1918; secret injection at a proxy; redact secrets from transcripts
- The five-axis local->remote diff: (1) sandboxing (node-locked Xpress/Gurobi dies in the microVM), (2) secrets/data egress (embargoed data must not leave the machine), (3) cost (commits = CI runs = solves), (4) async-PR-review-with-evidence vs live-diff watching, (5) determinism (temperature=0 insufficient: IEEE-754 float non-associativity -> guardrails + audit traces, assert objective within tolerance not the x-vector)

## Session 4 — Deploying Code
- 'Deploy' for OR = a merge to main that re-solves the canonical instance on a pinned OPEN solver and regenerates the study artifact behind a gate chain (a live /solve API or dashboard is a stretch on top)
- GitHub Actions anatomy: triggers (push/pull_request), jobs, needs: for a sequenced gate chain, per-job permissions, required status checks on protected main; deploy structurally unreachable until every gate is green
- The shift-left gate chain order: secret-scan (Gitleaks/TruffleHog, fetch-depth:0 over full history) -> lint+type-check (ruff/ty + actionlint on the YAML itself) -> SAST (CodeQL) -> SCA -> OR solve-contract + metamorphic gate -> container build+scan (Trivy) -> IaC validate (Checkov; tfsec folded into Trivy, Terrascan archived) -> gated deploy
- OR-specific deploy gate: solve contract (status whitelist, independent feasibility re-check, integrality, gap bound, objective tolerance) + metamorphic relations as required checks; 'wrong' (DQ/hard-red) vs 'slow' (warn/quarantine)
- GitHub->AWS OIDC keyless auth: IAM OIDC provider for token.actions.githubusercontent.com; role with sub-pinned trust policy (no wildcard — reproduce the vulnerability live); permissions: id-token: write; configure-aws-credentials action; missing id-token: write is the #1 failure
- AWS compute selection mapped to workload: S3 (private) + CloudFront via OAC for a static study dashboard (the cheap, reproducible default); Lambda container image (15-min ceiling, cold starts) for fast solves; ECS Fargate / App Runner for a steady /solve API; AWS Batch (EC2 + Spot) for the heaviest async MILP
- ECR push + ECS rolling deploy: tag image with commit SHA, render task definition, update service, rollback on smoke-test drift
- Solver licensing in the cloud: node-locked/static fails on ephemeral runners; Gurobi WLS (token-based, secrets, outbound HTTPS to token endpoint); FICO Xpress key-based licensing; most academic licenses lack the entitlement; Codex cloud strips even that -> OPEN solvers always (HiGHS, OR-Tools CP-SAT, CBC/PuLP), ~10x-100x slower so cloud runs small instances; the solver VERSION is part of the reproducible environment
- Container + supply-chain hardening: multi-stage non-root pinned Dockerfile (no :latest), Buildx multi-arch, Trivy (block CRITICAL/HIGH), SBOM; SHA-pin third-party actions (the March 2025 mutable-tag incident; SHA-pinned workflows were spared), read-only GITHUB_TOKEN, Cosign keyless signing, SLSA provenance, OpenSSF Scorecard weekly
- GitHub Environments: required reviewers, prevent-self-review, wait timer, branch restriction; approval pause consumes no billable minutes
- Agent-as-DevOps: the agent writes the workflow YAML + multi-stage Dockerfile + IaC + least-privilege IAM (per-permission justification) and reviews terraform plan / cdk synth in headless mode (claude -p, --allowedTools Bash,Read); its own YAML/IaC is gated by the same chain (cannot ship static keys, bypass branch protection, or merge a model that fails the solve contract)
- Reproducibility/solve smoke test as the deploy verifier: cold-start, POST a canned instance, assert recorded status + objective within tolerance under a wall-clock cap on a pinned solver/runtime; one-command rollback; cost hygiene (terraform destroy, instance-size + timeout caps as DoS protection)

## Session 5 — The Arena (Capstone Game)
- 'The Arena' (the single chosen format): a dynamic/rolling-horizon optimization tournament on the P01-P05 pack; instructor owns the protected engine/ (discrete-event simulator + scorer + leaderboard CI); each student owns one policies/<name>/ module behind a frozen Policy interface
- Dynamic / rolling-horizon optimization: re-optimize each wave under uncertainty about future arrivals — a POLICY, not a single MILP solve (the EURO-NeurIPS-2022 VRP dynamic variant)
- Held-out generalization split (Kaggle public/private ported to OR): tune on a public set with a live board, rank on a sealed private stream revealed on Demo Day; the 'shake-up' as the lesson that a green board is necessary, not sufficient — the OR echo of the Session-2 distrust-the-leaderboard reflex
- Tournament scoring backbone: solve-contract + metamorphic-invariant gates as ELIGIBILITY/disqualifiers; mean & p90 cost on the private stream as RANK; the wrong-vs-slow split as the rulebook (wrong => DQ, slow-but-correct => ranked lower)
- Per-wave wall-clock deadline + total compute budget + hard MIPGap/time cap as a GAME RULE that makes solver-muscle non-dominant; open-solver-only in the Arena (Xpress stays local — the S4 licensing reality)
- Remote/headless agent loop as the self-improvement engine: claude -p headless + anthropics/claude-code-action in ephemeral runners; issue -> sandboxed agent -> self-verified PR -> leaderboard re-score on merge (the competition runs on the S4 deploy pipeline)
- Deep-research-agent -> coding-agent -> leaderboard pipeline: background research on dispatch/look-ahead policies feeds the issue a remote agent then implements (callback to S2)
- Containerized, reproducible submission scoring on a pinned CPU core / open solver / seed; nondeterminism beyond tolerance => DQ (the S2 determinism spine as an eligibility check)
- Dual-rank leaderboard (static + dynamic averaged, EURO-NeurIPS-2022 style); the protected-main / /ship / guard-main.sh spine already live in this repo as the tournament's integrity layer
- Demo Day: 3-min talk; RESULTS.md reproduces the recorded objective; PR history spans all five rungs (>=1 local-authored, >=1 red-then-green by leaderboard CI, >=1 remote-agent-authored from an issue); placement is glory, the reproducible artifact + spanning PR history is the pass
- Precedents: EURO Meets NeurIPS 2022 VRP (static+dynamic dual-rank, containerized submissions), ROADEF/EURO Challenge (known+unknown instance split), Kaggle public/private 'ladder', SWE-bench contamination-resistant successors


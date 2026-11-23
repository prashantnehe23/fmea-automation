# ADR-035: Continuous Integration, Pinned Dependencies, Container Smoke Test, Dependency Audit

**Status:** Accepted (engineer, 2026-11-23: "Accept ADR-035, start B-058"), as written  **Date:** 2026-11-23  **Backlog:** B-058 (design review gap G5; enables B-059, B-062)  **Builds on:** [ADR-026](ADR-026-deployment-model.md) (the image), [ADR-031](ADR-031-frontend-test-framework.md) (JS tests)

## Context
Every "tests pass" in this project's history rests on one Windows machine. There is no `.github/` folder, so nothing checks a pull request; the container image (B-042) has never been built by anything but its author, and was never started in a test; `requirements.txt` uses lower bounds (`>=`) for most packages, so two installs a month apart can differ, and a new machine (the engineer's MacBook) can get versions nobody tested. The Windows machine, the Mac and the container are three different environments that currently share no check.

## Decision
1. **GitHub Actions**, one workflow (`.github/workflows/ci.yml`), on every pull request and every push to `main`. The repository is public, so runner minutes are free. Jobs:
   - **python-tests** on Linux with Python 3.11 (the documented floor) and 3.12 (the image), and on macOS with 3.12 (the engineer's other machine): `pytest`.
   - **web** on Linux with Node 20 (the image): `npm ci`, `npm test`, `npm run build`.
   - **image**: `docker build`, start the container with a throwaway data volume, run the smoke test below, stop it.
   - **audit**: dependency audit, below.
   All jobs must pass; the pull request check is required on `main` by the engineer in the repository settings (a setting, not code).
2. **Python dependencies are pinned exactly (`==`) for every package named in `requirements.txt`**, at the versions the suite passes with today. Test-only packages (`pytest`, `httpx`) go in `requirements-dev.txt`, also pinned, so the image does not carry them. Packages that these pull in are not locked.
3. **Dependency audit:** `pip-audit` (maintained by the Python Packaging Authority) against both requirements files, and `npm audit --omit=dev --audit-level=high` for the shipped frontend dependencies. The development tool chain's advisories (ADR-031) are reported but do not fail the job. A known-vulnerable pin fails the audit job.
4. **Container smoke test** (`scripts/smoke_container.py`, standard library only): against the running container it checks the health route, that a fresh install asks for its first administrator, creates one, signs in, points the app at a **fake model server**, runs one small scan and expects a finished result. The fake model server is a few dozen lines in `scripts/fake_model_server.py` that speaks the OpenAI chat protocol and returns canned replies; it needs no key and costs nothing, and it is also what makes the smoke test deterministic. It proves the image starts, the database is created, sign-in works and a scan completes end to end; it does not judge scan quality.
5. **Nothing in CI uses a real model key** and no secret is stored in the repository settings for this workflow.

## Alternatives considered
- **Another CI service (CircleCI, Jenkins):** extra accounts and setup; GitHub Actions is where the repository already lives.
- **A full lock file with hashes (`pip-compile`, `uv`, Poetry):** the strongest reproducibility, but adds a tool the team does not use yet, and a lock made on Windows can carry Windows-only packages. Exact pins on the named packages are a smaller step; a lock file can follow.
- **Only Linux runners:** cheaper, but the engineer's second machine is a Mac and the first Mac run already surprised us (a sign-in page where setup was expected).
- **Testing the container against a real model:** realistic but needs a secret, costs money on every push and is not deterministic.
- **Dependabot or Renovate for upgrades:** useful once pins exist; not part of this decision.

## Consequences
- A pull request that breaks Python 3.11, the Mac or the image is caught before merge, which today nobody would notice.
- Exact pins stop silent upgrades. A dependency update becomes a deliberate change, and the audit job tells us when a pin has a known flaw.
- Transitive packages can still change between runs; if that causes a failure, a lock file is the next step.
- CI takes several minutes per pull request (the Python suite alone takes about two minutes here).
- The fake model server and the smoke test are new code that must be kept in step with the API; they are small and tested by running in CI.
- Branch protection (making the check required) is a GitHub setting only the repository owner can switch on; until then the check informs but does not block.

## Decided
Accepted with all five points as written, including the Mac and Python 3.11 jobs, exact pins without a lock file, and a canned fake model for the smoke test.

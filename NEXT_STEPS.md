# Lawdocs next-step plan

## Current position

Lawdocs runs at https://lawdocs.dock108.dev with no login. The shared job list and downloads are publicly accessible. Entire server jobs expire 48 hours after upload; local retention remains independent.

The app combines a shared Python server, crash and plea engines, and browser JavaScript. Tests exist in several folders, but full-project coverage has not been measured. The workspace currently sits inside the Desktop Git repository, with no configured remote. There is no project GitHub Actions pipeline yet.

This document is a plan. Repository creation, CI implementation, and redesign are not part of the login-removal change.

## 1. Establish the project and reach 80% unit coverage

Create a dedicated private GitHub repository for Lawdocs. Include application source, deployment definitions, blank templates, public reference tables, and synthetic test fixtures. Exclude uploaded reports, saved results, credentials, local environments, and historical evidence.

Create one repeatable test command covering the shared server, delivery generation, retention, both engines, and browser behavior. Extract the inline browser logic into a testable module without changing its behavior. Replace tests that depend on personal files, existing output folders, or Mac-specific paths with self-contained fixtures.

Measure the baseline before setting priorities. Require at least **80% line coverage and 80% branch coverage** for Python and JavaScript separately, with the same minimum for each major application component. Include unimported source files in the denominator. Exclude only tests, generated/vendor code, and documented platform bootstrap code—not difficult business logic. Measure unit tests separately so integration tests do not inflate the unit-coverage claim.

Prioritize meaningful tests for:

- Crash injury/contributing-code rules, driver versus passenger matching, household grouping, apartment separation, and uncertain evidence.
- Native-text, scanned, sideways, and mixed plea calendars; charge grouping; missing fields; PDF name placement.
- Output names, newest-first ordering, workbook values, proof/source mapping, and unchanged originals.
- Retention at the exact 48-hour boundary, restart behavior, legacy timestamps, and expired downloads.
- Upload validation, interrupted processing, error states, and browser upload/download interactions.

Keep real OCR and rendered-document regression checks separate from unit tests. Mock external OCR calls in units; run deterministic synthetic PDFs through the actual Linux engines in integration tests. Cover the Mac adapter on a macOS runner if it remains supported.

**Done when:** a clean checkout runs every suite, produces coverage reports for all application components, and fails when any required threshold is missed. Coverage is a minimum, not proof of OCR accuracy.

## 2. Complete GitHub Actions CI and deployment

Build the pipeline in stages:

1. **Every pull request:** formatting/lint checks, Python and JavaScript unit tests, coverage gates, dependency checks, Linux OCR/PDF/workbook integration tests, and browser tests. Retain only synthetic failure artifacts with short retention.
2. **Build once:** produce a versioned release artifact from the tested commit. Pin dependencies, OCR models, runtime versions, and action revisions. Install dependencies and models during the build/setup stage, not the first user upload.
3. **Fresh installation check:** provision a clean disposable Linux environment with the deployment script, install the release, start services, and verify upload → processing → download plus expiry. This must work without files from the developer's Mac or an existing server installation.
4. **Automatic production deployment:** deploy passing main-branch commits to Hetzner using a dedicated restricted deploy identity stored in GitHub environment secrets. Verify the SSH host identity. Serialize deployments and keep deployment secrets unavailable to pull-request jobs.
5. **Safe release switch:** use versioned release directories and separate persistent job storage. Drain active processing before switching. Check health and a synthetic end-to-end download after activation; automatically return to the previous release if checks fail. Keep a small bounded number of old releases without copying job data into them.
6. **Fresh-host workflow:** provide a manually triggered GitHub Actions workflow that bootstraps a new authorized Hetzner host, installs Caddy and service definitions, deploys the same artifact, and verifies HTTPS. One-time GitHub repository access, deploy credentials, and DNS/host configuration are setup inputs; routine releases need no manual SSH commands.

Preserve the no-login behavior and 48-hour whole-job expiry through deploys and rollbacks. Preserve original upload timestamps. Do not restore expired data from a release or backup.

GitHub supports deployment environments, protection rules, and concurrency controls for this flow: [GitHub deployment documentation](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments).

**Done when:** a passing commit deploys automatically, a failed check blocks deployment, a deliberately failed release rolls back, and the same workflow can install onto a clean host. Record the deployed commit in the health response.

## 3. Give Lawdocs a simple, professional visual identity

Design it as a focused legal-document workspace: restrained typography, warm white surfaces, dark ink text, one muted accent, fine separators, and deliberate spacing. Avoid a marketing hero, dashboard tiles, decorative gradients, and unnecessary animation.

Use a compact Lawdocs header, one clear upload area with the two report types, and a clean results list below. Give filenames and status the most space; make upload time, deletion time, and the download action easy to scan. Display processing, empty, error, and expired states in plain language. Keep the 48-hour notice visible beside upload and results.

Prepare one considered desktop and mobile design using realistic filenames and long processing states. After visual review, implement reusable typography, spacing, color, button, and status styles. Keep the existing workflows; a frontend framework is not required just for this redesign.

Verify keyboard navigation, focus states, contrast, narrow screens, long filenames, upload progress, and downloads. Add browser and screenshot checks to the pipeline, alongside a human visual review.

**Done when:** the page feels cohesive and specific to Lawdocs, works on mobile and desktop, and makes upload → status → download obvious without adding steps.

## Recommended order

Create the standalone repository and synthetic fixtures → measure and reach the coverage gates → automate fresh installs, deployments, and rollback → review and implement the redesign through that pipeline.

The first implementation milestone is a clean checkout that can run all tests and report the real coverage baseline. That establishes the remaining test work before estimating the full delivery schedule.

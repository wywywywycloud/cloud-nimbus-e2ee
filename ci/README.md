# CI/CD integration

`.github/workflows/checks.yml` is the proposed active workflow; `ci/github-actions.yml`
is its identical reviewable copy. Neither has been pushed or run in GitHub by this task.
Publishing requires a credential with permission to change workflows.

Both `verify` (backend, migration drift, client unit tests, browser and delivery/tamper
checks) and `postgres` (full backend suite plus PostgreSQL row-lock/partial-index
checks in a disposable PostgreSQL 18 service) must succeed. Python 3.14 / Node 22 match
the intended host. The browser stand explicitly uses disposable SQLite; it is not a
PostgreSQL browser test. The client is pinned by the backend Git submodule commit;
update that gitlink only after reviewing/testing the actual client commit.

Actions are pinned by full commit SHA. Runtime and service major versions still
receive upstream updates; dependencies use existing Python and pnpm locks. Service
image digest pinning can be added after selecting the registry mirror/platform.
Artifacts contain JSON summaries only, no database, HAR, secrets or user files.

Deployment runs on pushes to `main`, after both jobs, through the `production`
environment. Configure protected `main`, required `verify`/`postgres` checks and
production environment deployment branch restriction `main` before enabling it.
Use required environment reviewers for the first deployment; changing that setting
to unattended releases is a separate operator decision. Fork PRs have no deployment
step or environment secrets. Concurrent deployments serialize; obsolete queued SHAs
are rejected by the host if `main` advanced.

Environment secrets:

- `NIMBUS_DEPLOY_KEY`: dedicated private SSH key for `nimbus-deploy`, never root.
- `NIMBUS_KNOWN_HOSTS`: host key for `13.143.141.139`, verified through a trusted
  console/channel. Do not obtain trust by blind `ssh-keyscan` during deployment.

Local checks: `OPAQUE_NODE=/path/to/node .venv/bin/python ci/check_deployment.py`.
PostgreSQL checks: on a **disposable** service only, set `POSTGRES_*`, then run
`python manage.py test ci.test_postgresql`. Never point test variables at production.
See `docs/DEPLOYMENT.md` for host preparation, failure handling and approval scope.

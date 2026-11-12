# Working on StudyNotes

- Read `README.md` and `DEV-README.md`; configuration/recovery details are in `docs/operations.md`.
- Keep this folder independently clonable. No parent-folder imports, personal
  resource IDs, credentials, generated deployment state or sibling data paths.
- Keep the design small: anonymous upload, Storage queue, one sequential worker,
  static results. No login, Durable Functions, database or frontend framework.
- Preserve the full transcript, source offsets and timestamp links.
- Run `python -m unittest discover -s tests` and `node --test tests/web.test.mjs`.
- Use provider stubs in tests. Deployments and paid AI calls require an explicit
  user request. `manage.py verify` must never submit media or invoke AI.
- Keep credentials in Azure/ignored local settings. Package using the explicit
  allowlist in `manage.py`; never zip the working directory indiscriminately.
- Cleanup may remove only resources owned by this deployment; preserve reused
  Foundry resources. Never upgrade a subscription or remove its spending limit.
- Keep the README concise; add reference details to the operations page.

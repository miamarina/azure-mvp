# Developer guide

Run commands from this folder. Use **Python 3.12**, **Node 22+** for JS tests,
and **Azure CLI 2.90+** for cloud management. See the [architecture](ARCHITECTURE.md).

## Edit and preview

```sh
python -m venv .venv
```

Activate: PowerShell `.venv\Scripts\Activate.ps1`; macOS/Linux
`source .venv/bin/activate`. Then:

```sh
python -m pip install -r requirements.txt
python manage.py preview
```

Open [localhost:8080](http://127.0.0.1:8080). Edit `web/` and refresh; no frontend
build is needed. Preview serves the saved `sample/` only. Backend development
uses stubbed tests; these local workflows need no Azure credentials or AI calls.

## Find the code

| Change | Files / tests |
| --- | --- |
| Transcript rules, chapter validation, job IDs | `core.py` / `tests/test_core.py` |
| Upload validation and queue binding | `function_app.py` / `tests/test_upload.py` |
| Storage, FFmpeg, Speech and model calls | `pipeline.py` / `tests/test_pipeline.py` |
| Reader, search, export and upload retries | `web/` / `tests/web.test.mjs` |
| Provisioning, packaging and cleanup | `manage.py`, `host.json`, `config.example.json` / `tests/test_manage.py` |

## Check a change

```sh
python -m unittest discover -s tests
node --test tests/web.test.mjs
```

Add focused tests for changed behavior using the existing provider stubs. For UI
changes, also check the preview. Describe behavior and validation in the PR, and
update affected docs alongside the code. Keep the [design rules](AGENTS.md).

## Deploy a change

Complete [Azure login and configuration](README.md#deploy-your-own-copy) first.
Keep the same subscription/project name to update your existing deployment.

```sh
python manage.py plan
python manage.py deploy
```

`plan` prints resource names/settings without querying Azure. `deploy` performs a Linux
remote build, publishes the reader and runs read-only readiness checks. Existing
lecture files/catalog are preserved. Run `python manage.py verify` to repeat
readiness checks; it does not exercise fresh AI processing.

When adding files, update `BACKEND_FILES` / `SHARE_FILES` in `manage.py` as needed.
Preserve ZIP permissions (`0644`) so the Linux host can read `host.json`.

## Debug and hand over

Use the job ID from the upload response. Inspect private
`studynotes/jobs/<id>/metadata.json`, `timing.json`, and `speech-*` / `summary-*`
receipts; check `lectures` / `lectures-poison` for queue failures. Deployment
state and verification receipts are under `.local/<deployment-id>/`.

New jobs invoke paid AI. Duplicate IDs include bytes, language, `core.VERSION`
and Trial ID; changing the latter two permits new billable work. Keep claim and
attempt markers intact while investigating failures.

Run `python manage.py package` for a clean handover ZIP. Commit source/docs;
keep personal `config.json`, credentials, `.venv/` and `.local/` untracked.
For configuration, cold starts, recovery, data export and scoped cleanup, use
the [operations reference](docs/operations.md).

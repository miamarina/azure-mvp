# StudyNotes 2.0

Turn a recording into a complete, searchable lecture scriptum with chapters,
an overview, key terms and links to the original video. For Group 15's tests
and experiments: no login, database or frontend framework.

**Browser upload → Azure Storage queue → one Python worker → static reader.**
The worker uses Azure Speech and GPT-5 mini. Reading/searching reuses saved
files. A [saved example](sample/ATTRIBUTION.md) is included; previewing it costs
no AI calls.

[Architecture diagram and explanation](ARCHITECTURE.md).

## Try the reader locally

Requires **Python 3.12**. From this folder:

```sh
python manage.py preview
```

Open [localhost:8080](http://127.0.0.1:8080). Search, chapter navigation and
Markdown export work immediately. Uploads require an Azure deployment.

## Deploy your own copy

You need [Azure CLI **2.90+**](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli), an enabled subscription and available Functions,
Speech and GPT-5 mini quota in the chosen region. Each teammate deploys to their
own subscription; credentials and credits are not shared.

```sh
python -m venv .venv
```

Activate it: Windows PowerShell `.venv\Scripts\Activate.ps1`; macOS/Linux
`source .venv/bin/activate`. Then:

```sh
python -m pip install -r requirements.txt
az login
cp config.example.json config.json
```

Edit `config.json`: set **your subscription ID** and a unique **project_name**.
Leave the spending limit on. Deployment creates a dedicated resource group,
storage, Function App and Foundry/model deployment; see
[configuration and reused Foundry resources](docs/operations.md).

```sh
python manage.py plan
python manage.py deploy
```

The last command prints the reader URL and runs read-only readiness checks.
Uploads are anonymous and outputs publicly readable: use permitted test
material. **A new upload invokes paid AI services.** No paid calls run during
deploy, preview or verify. No subscription upgrade is performed.
Cold starts may delay an upload; transient failures retry the same job.

## Test and inspect

```sh
python -m unittest discover -s tests
node --test tests/web.test.mjs
python manage.py verify
```

Node 22+ is needed only for the browser-logic tests. Python tests use provider
stubs. `verify` checks the deployed health/assets/example, not AI accuracy or a
fresh full processing run. Long inputs and German quality need evaluation.

The upload form accepts recordings up to the configured limits (defaults:
90 minutes / 200 MiB). Normal duplicates reuse saved jobs. Set an optional
**Trial ID** only when intentionally measuring a new processing run.

## Save data and stop costs

```sh
python manage.py export
```

After the export succeeds, remove your deployment using its exact group name:

```sh
python manage.py destroy --confirm rg-studynotes-yourname
```

Cleanup preserves reused Foundry resources and local exports. Keep `.local/`
until cleanup is complete. [Limits, troubleshooting and recovery](docs/operations.md).

## Share or change it

Commit **this folder's contents** as the repository root. `.gitignore` excludes
personal config, credentials, environments and deployment state. For a clean
handover ZIP, run `python manage.py package`. The folder has no parent-project
dependencies. [Developer workflow](DEV-README.md) · [Agent guidance](AGENTS.md).

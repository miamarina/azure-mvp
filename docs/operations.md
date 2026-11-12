# Configuration and operations

## Configuration

Copy `config.example.json` to the ignored `config.json`. Run commands from the
repository root. Resource names are derived from project name + subscription;
do not change these while a deployment is running. State/receipts/exports stay
in `.local/<deployment-id>/` and contain no saved login tokens or storage keys.

| Setting | Default / meaning |
| --- | --- |
| `subscription_id` | Required; your subscription UUID. Every CLI command is scoped to it. |
| `project_name` | Required; 4–24 lowercase letters/digits/hyphens. Its group is `rg-<name>`. |
| `location` | `swedencentral`; use a region supporting the selected services/models. |
| `hosting` | `flex`; Python 3.12, 2 GiB, no always-ready instances. `consumption` is an explicit legacy fallback with a ten-minute execution timeout. |
| `max_instances` | `2`; raise deliberately for experiments. Flex applies its ceiling per scale group, not globally across HTTP and queue workers. Each worker instance processes one job at a time. |
| `max_upload_mib` / `max_audio_minutes` | `200` / `90`; admission ceilings, not demonstrated performance. |
| `model_capacity` | `10`; GPT-5 mini Global Standard throughput allocation, not dedicated servers. |
| `require_spending_limit` | `true`; refuse deployment unless the spending limit is On. Set false only for an already-approved subscription without that facility; this never upgrades it. |
| `existing_foundry` | `null` creates a resource in this group. To reuse one, set `{"resource_group":"YOUR-GROUP","account":"YOUR-ACCOUNT"}`. It must be an AIServices resource supporting Speech/OpenAI. |

Deployment uses GPT-5 mini `2025-08-07`, Global Standard. Model availability and
quota are subscription/region dependent. Global Standard does not guarantee
EU-only processing. The script creates only its uniquely named summary
deployment and worker roles in a reused resource; cleanup preserves the account.

Standard Azure CLI is used. An optional `AZURE_CLI_PYTHON` environment variable
can point to the Python bundled with a ZIP/Windows CLI installation. An existing
`AZURE_CONFIG_DIR` is respected. Neither belongs in committed configuration.

## What runs

- `function_app.py`: anonymous `POST /api/jobs`, read-only `GET /api/health`, queue binding.
- `pipeline.py`: FFmpeg → Speech → chapter structure/overview/terms → validation → saved results.
- `core.py`: validation, duplicate IDs and absolute source links.
- `web/`: static reader; `sample/`: attributed saved example.
- `manage.py`: provisioning, Linux remote build, publication, verification and scoped cleanup.

One storage account holds private `studynotes/jobs/<id>/` inputs, normalized WAV,
raw responses and attempt/timing receipts. Public `$web` holds assets,
`catalog.json` and `lectures/<id>.json`. Only upload handlers edit the catalog;
conditional ETags prevent lost updates. Workers publish separate lecture files.

Application storage/AI calls use the Function's managed identity. Host queue
storage/deployment may use Azure-generated connection settings. Those stay in
Azure; no service credentials are sent to the reader. CORS permits the reader
origin and is not authentication. This is intentionally a group test deployment.

## Limits and experiments

The full transcript remains intact; the model returns chapter boundaries rather
than a shortened substitute. References and chapter order are validated, not
factual truth. The saved example is an offline adaptation, not a new AI test.

Speech admits audio shorter than two hours / smaller than 250 MB. The worker
normalizes to 16 kHz mono PCM and caps preparation at 300 seconds. Speech has a
600-second read timeout; notes have 300 seconds, 350,000 transcript characters
and 4,096 completion tokens. Test representative full lectures before claiming
support within the configured limits. Original video uploads must also fit
Functions HTTP limits and the client's upload timeout; larger originals need a
direct-to-Blob ingestion extension, which this version does not implement.

For copied excerpts, set **Excerpt starts at** to the position in the original
recording. Links add that offset to transcript time. Supported sources are
YouTube watch/share links and direct media files. The reader plays the original
source; it does not expose the private uploaded media. An external host can
disable embedding; the source links still open its original page.

Duplicates are keyed by bytes + language + processing version + optional Trial
ID. Title/attribution changes do not create another paid job. Use distinct Trial
IDs for timing trials; keep conditions fixed. Queue `batchSize=1` and the
instance ceiling bound configured concurrency. They are not a
monthly budget, global provider admission controller or measured throughput.

## When something fails

| Symptom | Action |
| --- | --- |
| No Functions/model quota | Inspect quota/region in Azure; use another eligible environment or explicitly choose a supported plan. Do not upgrade automatically. |
| CLI login expired | Run `az login` for your own subscription and repeat the command. |
| Upload slow or service unavailable | On-demand cold starts can be slow. The browser retries transient gateway/network failures at most twice, keeping the same file/language/Trial ID. If it still fails, retry with those same values; duplicates reuse the job. |
| Upload accepted but waiting | Allow cold start/role propagation. Check Functions logs, queue `lectures` / `lectures-poison`, and the private job metadata. |
| Failed or uncertain AI attempt | Inspect private `*-attempt.json`, `*-raw.json`, `*-timing.json` and `*-error.json` before any rerun. A new Trial ID deliberately permits new billable requests. |
| Preview upload is disabled | Expected: the offline preview has saved data only. Use the deployed URL for uploads. |

Each worker claims its job atomically. Queue redelivery cannot start concurrent
paid work for that ID. An AI attempt without a saved response stops rather than
automatically retrying. There is one automatic queue processing attempt; failed
jobs retain their claim and intermediate data for owner review. This accepts
manual recovery and does not claim exactly-once provider execution. Do not
delete attempt/claim markers casually to force another run.

`export` downloads private inputs/results and public files before cleanup.
`destroy` checks the group ownership tag, deletes only recorded worker roles
and the owned summary deployment on reused Foundry resources, then deletes its
group. It does not delete local files or unrelated resources. Billing may show
earlier usage after deletion.

## References

[Functions hosting/limits](https://learn.microsoft.com/en-us/azure/azure-functions/functions-scale) ·
[Queue retries](https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-storage-queue) ·
[Speech limits](https://learn.microsoft.com/en-us/rest/api/speechtotext/transcriptions/transcribe) ·
[Global Standard](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/deployment-types).

Documentation follows [GitHub's README guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)
and [Diátaxis task-focused how-to guidance](https://diataxis.fr/how-to-guides/):
quick start in the README; reference and troubleshooting here.
The [developer guide](../DEV-README.md) follows
[Google's documentation practices](https://google.github.io/styleguide/docguide/best_practices.html):
short, current instructions with links instead of duplicated reference material.

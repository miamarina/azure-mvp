"""Preview, deploy, verify, export and remove this independently clonable app."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parent
BACKEND_FILES = ("function_app.py", "pipeline.py", "core.py", "host.json", "requirements.txt")
SHARE_FILES = (*BACKEND_FILES, "manage.py", "README.md", "DEV-README.md", "ARCHITECTURE.md", "AGENTS.md", "config.example.json", ".gitignore", ".funcignore")
SHARE_DIRS = ("web", "sample", "docs", "tests", ".github")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def config(path):
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    uuid.UUID(cfg["subscription_id"])
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,22}[a-z0-9]", cfg["project_name"]):
        raise ValueError("project_name must be 4-24 lowercase letters/digits/hyphens, starting with a letter.")
    cfg.setdefault("location", "swedencentral")
    cfg.setdefault("hosting", "flex")
    if cfg["hosting"] not in {"flex", "consumption"}:
        raise ValueError("hosting must be flex or consumption.")
    for name, default, minimum, maximum in (("max_instances", 2, 1, 20), ("max_upload_mib", 200, 1, 200),
            ("max_audio_minutes", 90, 1, 90), ("model_capacity", 10, 1, 100)):
        cfg.setdefault(name, default)
        if type(cfg[name]) is not int or not minimum <= cfg[name] <= maximum:
            raise ValueError(f"{name} must be an integer between {minimum} and {maximum}.")
    cfg.setdefault("require_spending_limit", True)
    return cfg


def names(cfg):
    identity = hashlib.sha256(f"{cfg['subscription_id']}/{cfg['project_name']}".encode()).hexdigest()[:12]
    return {"identity": identity, "resource_group": "rg-" + cfg["project_name"],
        "storage": "sn2" + identity, "function_app": cfg["project_name"] + "-" + identity[:6],
        "foundry": "sn2-ai-" + identity, "model_deployment": "summary-" + identity[:6]}


def state_path(cfg):
    return ROOT / ".local" / names(cfg)["identity"] / "state.json"


def function_hostname(function):
    # Azure CLI versions return either flattened or ARM-shaped properties.
    properties = function.get("properties") or function
    hostname = properties.get("defaultHostName") or properties.get("defaultHostname")
    if not hostname:
        raise RuntimeError("The Function App has no default hostname yet; repeat deploy after provisioning completes.")
    return hostname


def azure_command():
    if os.getenv("AZURE_CLI_PYTHON"):
        return [os.environ["AZURE_CLI_PYTHON"], "-IBm", "azure.cli"]
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Install Azure CLI and run az login first (see README).")
    if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
        # Invoke its Python directly, avoiding cmd.exe quoting for JSON bodies.
        for candidate in (Path(executable).parent.parent / "python.exe", Path(executable).parent / "python.exe"):
            if candidate.is_file():
                return [str(candidate), "-IBm", "azure.cli"]
        raise RuntimeError("Set AZURE_CLI_PYTHON to the python.exe shipped with Azure CLI.")
    return [executable]


class Cloud:
    def __init__(self, cfg):
        self.cfg, self.command, self.secrets = cfg, azure_command(), []

    def run(self, *args, timeout=900):
        env = os.environ.copy()
        env.update(AZURE_CORE_COLLECT_TELEMETRY="no", AZURE_CORE_ENABLE_BROKER_ON_WINDOWS="false",
                   AZURE_CORE_LOGIN_EXPERIENCE_V2="off")
        result = subprocess.run([*self.command, *args, "--subscription", self.cfg["subscription_id"],
            "--output", "json", "--only-show-errors"], env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout)
        if result.returncode:
            error = result.stderr.strip() or "Azure CLI failed."
            for secret in self.secrets:
                error = error.replace(secret, "[redacted]")
            raise RuntimeError(error)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def rest(self, method, path, body=None):
        args = ["rest", "--method", method, "--url", "https://management.azure.com" + path]
        if body is not None:
            args += ["--body", json.dumps(body, separators=(",", ":"))]
        return self.run(*args)

    def storage(self, account, group):
        from azure.storage.blob import BlobServiceClient
        keys = self.run("storage", "account", "keys", "list", "--resource-group", group, "--account-name", account)
        self.secrets.extend(key["value"] for key in keys)
        endpoints = self.run("storage", "account", "show", "--resource-group", group,
            "--name", account, "--query", "primaryEndpoints")
        return BlobServiceClient(endpoints["blob"], credential=keys[0]["value"]), endpoints, keys[0]["value"]


def save_state(cfg, state, **updates):
    state.update(updates)
    write_json(state_path(cfg), state)


def backend_package(cfg, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in BACKEND_FILES:
            # Flex runs as a different Linux user from the remote builder.
            # ZipFile.writestr defaults to 0600, making host.json unreadable.
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            if name == "host.json":
                host = json.loads((ROOT / name).read_text(encoding="utf-8"))
                host["functionTimeout"] = "00:30:00" if cfg["hosting"] == "flex" else "00:10:00"
                content = json.dumps(host).encode()
            else:
                content = (ROOT / name).read_bytes()
            archive.writestr(entry, content)
    return target


def publish_web(service, state, cfg):
    from azure.storage.blob import ContentSettings
    types = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
             ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
             ".json": "application/json; charset=utf-8"}
    for path in sorted((ROOT / "web").rglob("*")):
        if not path.is_file():
            continue
        content = path.read_bytes()
        if path.name == "config.js":
            content = ("window.STUDYNOTES_CONFIG = " + json.dumps({"apiBase": state["api_url"],
                "maxUploadBytes": cfg["max_upload_mib"] * 1048576,
                "maxAudioSeconds": cfg["max_audio_minutes"] * 60}) + ";\n").encode()
        service.get_blob_client("$web", path.relative_to(ROOT / "web").as_posix()).upload_blob(content,
            overwrite=True, content_settings=ContentSettings(content_type=types.get(path.suffix, "application/octet-stream"),
                cache_control="no-cache"))
    # Never overwrite an existing catalog or any uploaded lecture when redeploying.
    from azure.core.exceptions import ResourceExistsError
    for path in sorted((ROOT / "sample").rglob("*.json")):
        try:
            service.get_blob_client("$web", path.relative_to(ROOT / "sample").as_posix()).upload_blob(
                path.read_bytes(), overwrite=False, content_settings=ContentSettings(
                    content_type="application/json; charset=utf-8", cache_control="no-store"))
        except ResourceExistsError:
            pass


def deploy(cfg):
    from azure.core.exceptions import ResourceExistsError
    from azure.storage.queue import QueueServiceClient
    n = names(cfg)
    cloud = Cloud(cfg)
    state = json.loads(state_path(cfg).read_text()) if state_path(cfg).exists() else {**n, "subscription_id": cfg["subscription_id"]}
    policy = cloud.rest("get", f"/subscriptions/{cfg['subscription_id']}?api-version=2022-12-01")
    if policy["state"] != "Enabled":
        raise RuntimeError("The selected subscription is not Enabled.")
    if cfg["require_spending_limit"] and policy["subscriptionPolicies"]["spendingLimit"] != "On":
        raise RuntimeError("Spending limit is not On; this script will not change the subscription.")
    print(f"Deploying {cfg['project_name']} in {cfg['location']} ({cfg['hosting']}, max {cfg['max_instances']} instance(s) per scale group)", flush=True)
    if cloud.run("group", "exists", "--name", n["resource_group"]):
        group = cloud.run("group", "show", "--name", n["resource_group"])
        if (group.get("tags") or {}).get("studynotes2") != n["identity"]:
            raise RuntimeError("Resource group already exists without this project's ownership tag. Choose another project_name.")
    else:
        cloud.run("group", "create", "--name", n["resource_group"], "--location", cfg["location"],
                  "--tags", "studynotes2=" + n["identity"], "purpose=group-testing")
    save_state(cfg, state, hosting=cfg["hosting"], stage="provisioning")
    providers = ["Microsoft.Storage", "Microsoft.Web", "Microsoft.CognitiveServices"]
    if cfg["hosting"] == "flex":
        providers.append("Microsoft.App")
    for namespace in providers:
        cloud.run("provider", "register", "--namespace", namespace, "--wait")
    print("Creating storage and queue", flush=True)
    cloud.run("storage", "account", "create", "--name", n["storage"], "--resource-group", n["resource_group"],
        "--location", cfg["location"], "--sku", "Standard_LRS", "--kind", "StorageV2",
        "--allow-blob-public-access", "false", "--min-tls-version", "TLS1_2", "--https-only", "true")
    service, endpoints, storage_key = cloud.storage(n["storage"], n["resource_group"])
    service.set_service_properties(static_website={"enabled": True, "index_document": "index.html", "error_document404_path": "index.html"})
    for name in ("studynotes", "$web"):
        try:
            service.create_container(name)
        except ResourceExistsError:
            pass
    queue = QueueServiceClient(endpoints["queue"], credential=storage_key)
    try:
        queue.create_queue("lectures")
    except ResourceExistsError:
        pass
    # The website endpoint appears after static hosting has been enabled.
    endpoints = cloud.run("storage", "account", "show", "--resource-group", n["resource_group"],
        "--name", n["storage"], "--query", "primaryEndpoints")
    save_state(cfg, state, reader_url=endpoints["web"].rstrip("/"))
    existing_apps = cloud.run("functionapp", "list", "--resource-group", n["resource_group"], "--query", "[].name")
    if n["function_app"] not in existing_apps:
        print("Creating the Function App", flush=True)
        arguments = ["functionapp", "create", "--name", n["function_app"], "--resource-group", n["resource_group"],
            "--storage-account", n["storage"], "--runtime", "python", "--runtime-version", "3.12",
            "--functions-version", "4", "--assign-identity", "--disable-app-insights", "true"]
        if cfg["hosting"] == "flex":
            arguments += ["--flexconsumption-location", cfg["location"], "--instance-memory", "2048",
                          "--maximum-instance-count", str(cfg["max_instances"])]
        else:
            arguments += ["--consumption-plan-location", cfg["location"], "--os-type", "Linux"]
        cloud.run(*arguments)
    function = cloud.run("functionapp", "show", "--name", n["function_app"], "--resource-group", n["resource_group"])
    principal = (function.get("identity") or {}).get("principalId")
    if not principal:
        identity = cloud.run("functionapp", "identity", "assign", "--name", n["function_app"], "--resource-group", n["resource_group"])
        principal = identity["principalId"]
    save_state(cfg, state, principal_id=principal, api_url="https://" + function_hostname(function) + "/api")
    cloud.run("functionapp", "update", "--name", n["function_app"], "--resource-group", n["resource_group"], "--set", "httpsOnly=true")
    existing = cfg.get("existing_foundry")
    if existing:
        foundry_group, foundry_name = existing["resource_group"], existing["account"]
        ai = cloud.run("cognitiveservices", "account", "show", "--resource-group", foundry_group, "--name", foundry_name)
    else:
        print("Creating this deployment's Foundry resource", flush=True)
        foundry_group, foundry_name = n["resource_group"], n["foundry"]
        ai = cloud.run("cognitiveservices", "account", "create", "--resource-group", foundry_group,
            "--name", foundry_name, "--location", cfg["location"], "--kind", "AIServices", "--sku", "S0",
            "--custom-domain", foundry_name, "--yes")
    if ai.get("kind") != "AIServices":
        raise RuntimeError("The reused resource must be an AIServices Foundry account (Speech + OpenAI).")
    save_state(cfg, state, foundry_resource_group=foundry_group, foundry_account=foundry_name,
               foundry_id=ai["id"], foundry_reused=bool(existing))
    deployments = cloud.run("cognitiveservices", "account", "deployment", "list", "--resource-group", foundry_group, "--name", foundry_name)
    if any(item["name"] == n["model_deployment"] for item in deployments):
        if not state.get("model_owned"):
            raise RuntimeError("Model deployment already exists without local ownership state; refusing to replace it.")
    else:
        print("Creating this app's GPT-5 mini deployment (no inference)", flush=True)
        save_state(cfg, state, model_owned=True)
        cloud.run("cognitiveservices", "account", "deployment", "create", "--resource-group", foundry_group,
            "--name", foundry_name, "--deployment-name", n["model_deployment"], "--model-name", "gpt-5-mini",
            "--model-version", "2025-08-07", "--model-format", "OpenAI", "--sku-name", "GlobalStandard",
            "--sku-capacity", str(cfg["model_capacity"]))
    storage_id = f"/subscriptions/{cfg['subscription_id']}/resourceGroups/{n['resource_group']}/providers/Microsoft.Storage/storageAccounts/{n['storage']}"
    assignments = state.get("role_assignments", [])
    for role, scope in (("Storage Blob Data Contributor", storage_id), ("Storage Queue Data Contributor", storage_id),
                        ("Cognitive Services User", ai["id"]), ("Cognitive Services OpenAI User", ai["id"])):
        assignment_name = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{scope}/{principal}/{role}".lower()))
        assignment = cloud.run("role", "assignment", "create", "--name", assignment_name,
            "--assignee-object-id", principal, "--assignee-principal-type", "ServicePrincipal", "--role", role, "--scope", scope)
        if assignment["id"] not in assignments:
            assignments.append(assignment["id"])
            save_state(cfg, state, role_assignments=assignments)
    settings_path = function["id"] + "/config/appsettings"
    settings = cloud.rest("post", settings_path + "/list?api-version=2024-04-01")["properties"]
    settings.update({"BLOB_SERVICE_URL": endpoints["blob"], "QUEUE_SERVICE_URL": endpoints["queue"],
        "AI_ENDPOINT": f"https://{foundry_name}.cognitiveservices.azure.com",
        "OPENAI_ENDPOINT": f"https://{foundry_name}.openai.azure.com", "SUMMARY_DEPLOYMENT": n["model_deployment"],
        "MAX_UPLOAD_BYTES": str(cfg["max_upload_mib"] * 1048576), "MAX_AUDIO_SECONDS": str(cfg["max_audio_minutes"] * 60),
        "MAX_TRANSCRIPT_CHARS": "350000", "MAX_COMPLETION_TOKENS": "4096",
        "FUNCTIONS_REQUEST_BODY_SIZE_LIMIT": str(cfg["max_upload_mib"] * 1048576)})
    if cfg["hosting"] == "consumption":
        settings.update(WEBSITE_MAX_DYNAMIC_APPLICATION_SCALE_OUT=str(cfg["max_instances"]),
                        SCM_DO_BUILD_DURING_DEPLOYMENT="true", ENABLE_ORYX_BUILD="true", FUNCTIONS_WORKER_PROCESS_COUNT="1")
    cloud.secrets.extend(value for key, value in settings.items() if "connection" in key.lower() or key == "AzureWebJobsStorage")
    cloud.rest("put", settings_path + "?api-version=2024-04-01", {"properties": settings})
    if cfg["hosting"] == "flex":
        cloud.run("functionapp", "scale", "config", "set", "--name", n["function_app"], "--resource-group", n["resource_group"],
            "--maximum-instance-count", str(cfg["max_instances"]), "--trigger-type", "http", "--trigger-settings", "perInstanceConcurrency=1")
    cloud.run("functionapp", "cors", "add", "--resource-group", n["resource_group"], "--name", n["function_app"], "--allowed-origins", state["reader_url"])
    print("Publishing Python source with a Linux remote build", flush=True)
    package = backend_package(cfg, state_path(cfg).parent / "function.zip")
    cloud.run("functionapp", "deployment", "source", "config-zip", "--resource-group", n["resource_group"],
        "--name", n["function_app"], "--src", str(package), "--build-remote", "true", "--timeout", "1200", timeout=1500)
    print("Publishing static reader and saved sample", flush=True)
    publish_web(service, state, cfg)
    save_state(cfg, state, stage="deployed", deployed_at=datetime.now(timezone.utc).isoformat(),
               backend_sha256=hashlib.sha256(package.read_bytes()).hexdigest())
    print("Reader: " + state["reader_url"], flush=True)
    print("Deployment state: " + str(state_path(cfg)), flush=True)
    return state


def verify(cfg):
    import requests
    state = json.loads(state_path(cfg).read_text(encoding="utf-8"))
    checks = {}
    for attempt in range(12):
        try:
            result = requests.get(state["api_url"] + "/health", timeout=45)
            result.raise_for_status()
            checks["health"] = result.json()["version"] == "studynotes-2.0"
            break
        except requests.RequestException:
            if attempt == 11:
                raise
            print("Waiting for Functions startup", flush=True)
            time.sleep(5)
    for path in ("/", "/app.js", "/lib.mjs", "/styles.css", "/config.js", "/catalog.json"):
        response = requests.get(state["reader_url"] + path, timeout=30)
        response.raise_for_status()
        checks["reader" + path] = True
    catalog = requests.get(state["reader_url"] + "/catalog.json", timeout=30).json()
    assert catalog["lectures"], "Saved sample is missing."
    sample = requests.get(state["reader_url"] + "/lectures/vectors-sample.json", timeout=30)
    sample.raise_for_status()
    value = sample.json()
    from core import validate_notes
    validate_notes(value["notes"], value["transcript"])
    checks["saved_sample_and_chapter_coverage"] = value["job"]["sample"] is True
    assert all(checks.values())
    receipt = {"checked_at": datetime.now(timezone.utc).isoformat(), "checks": checks,
        "inference_calls": 0, "uploads_submitted": 0, "live_ai_pipeline": "Not exercised by this read-only check."}
    write_json(state_path(cfg).parent / "verification.json", receipt)
    print(json.dumps(receipt, indent=2))


def export_data(cfg):
    state = json.loads(state_path(cfg).read_text(encoding="utf-8"))
    service, _, _ = Cloud(cfg).storage(state["storage"], state["resource_group"])
    target = state_path(cfg).parent / "exports" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    count = 0
    for container in ("studynotes", "$web"):
        for item in service.get_container_client(container).list_blobs():
            destination = (target / container / item.name).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise ValueError("Unsafe blob path in export.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as output:
                service.get_blob_client(container, item.name).download_blob().readinto(output)
            count += 1
    print(f"Saved {count} blobs under {target}")


def destroy(cfg, confirmation):
    n = names(cfg)
    if confirmation != n["resource_group"]:
        raise ValueError("Pass --confirm with the exact resource group name from the deployment output/state.")
    cloud = Cloud(cfg)
    state = json.loads(state_path(cfg).read_text(encoding="utf-8"))
    exists = cloud.run("group", "exists", "--name", n["resource_group"])
    if exists:
        group = cloud.run("group", "show", "--name", n["resource_group"])
        if (group.get("tags") or {}).get("studynotes2") != n["identity"]:
            raise RuntimeError("Ownership tag mismatch: refusing cleanup.")
    # Remove only recorded, explicitly checked permissions on reused resources.
    if state.get("foundry_reused"):
        foundry_id = state["foundry_id"]
        current_assignments = cloud.run("role", "assignment", "list", "--all", "--query",
            f"[?principalId=='{state['principal_id']}']")
        for assignment_id in state.get("role_assignments", []):
            if assignment_id.lower().startswith(foundry_id.lower() + "/providers/microsoft.authorization/roleassignments/"):
                remaining = [item for item in current_assignments if item["id"].lower() == assignment_id.lower()]
                if remaining:
                    if remaining[0]["principalId"] != state["principal_id"]:
                        raise RuntimeError("Role assignment principal changed: refusing cleanup.")
                    cloud.run("role", "assignment", "delete", "--ids", assignment_id)
        if state.get("model_owned"):
            deployed = cloud.run("cognitiveservices", "account", "deployment", "list", "--resource-group",
                state["foundry_resource_group"], "--name", state["foundry_account"])
            if any(item["name"] == n["model_deployment"] for item in deployed):
                cloud.run("cognitiveservices", "account", "deployment", "delete", "--resource-group",
                    state["foundry_resource_group"], "--name", state["foundry_account"], "--deployment-name", n["model_deployment"])
    if exists:
        cloud.run("group", "delete", "--name", n["resource_group"], "--yes", timeout=1500)
    assert cloud.run("group", "exists", "--name", n["resource_group"]) is False
    save_state(cfg, state, stage="deleted", deleted_at=datetime.now(timezone.utc).isoformat())
    print("Deleted " + n["resource_group"] + "; local exports are retained.")


def share_package():
    target = ROOT / ".local" / "studynotes-share.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in SHARE_FILES:
            archive.write(ROOT / name, name)
        for name in SHARE_DIRS:
            for path in sorted((ROOT / name).rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    archive.write(path, path.relative_to(ROOT).as_posix())
    print(target)


class Preview(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "web"), **kwargs)

    def translate_path(self, path):
        public = path.split("?", 1)[0]
        if public == "/catalog.json" or public.startswith("/lectures/"):
            candidate = (ROOT / "sample" / public.lstrip("/")).resolve()
            if candidate.is_relative_to((ROOT / "sample").resolve()):
                return str(candidate)
        return super().translate_path(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "plan", "deploy", "verify", "export", "destroy", "package"))
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--confirm", default="")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    if args.action == "preview":
        print(f"Preview: http://127.0.0.1:{args.port} (saved sample; uploads need an Azure deployment)", flush=True)
        ThreadingHTTPServer(("127.0.0.1", args.port), Preview).serve_forever()
    elif args.action == "package":
        share_package()
    else:
        cfg = config(args.config)
        if args.action == "plan":
            print(json.dumps({**names(cfg), "subscription_id": cfg["subscription_id"], "hosting": cfg["hosting"],
                "location": cfg["location"], "max_instances": cfg["max_instances"], "existing_foundry": cfg.get("existing_foundry")}, indent=2))
        elif args.action == "deploy":
            deploy(cfg)
            verify(cfg)
        elif args.action == "verify":
            verify(cfg)
        elif args.action == "export":
            export_data(cfg)
        elif args.action == "destroy":
            destroy(cfg, args.confirm)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError, FileNotFoundError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)

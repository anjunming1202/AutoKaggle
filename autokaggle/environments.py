"""Environment challenges: seeds replace data samples, and submissions are pinned GitHub commits.

The web service reads repository metadata and one manifest. It never clones or runs a repository.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import random
import re
import sys
from urllib.parse import quote

from . import environment_harness as harness
from . import sources

MANIFEST = "autokaggle-submission.json"
MANIFEST_FORMAT = "autokaggle.environment-submission.v1"
METRICS = ("success_rate", "mean_score")
SEED_LIMIT = 2 ** 63 - 1
MIN_RANGE_MULTIPLE = 10
SEED_RULES = ("A seed is the evaluation unit. Each seed is one independent episode in the same environment version. "
              "Train on any seed outside the reserved range. Evaluation seeds come from the reserved range and stay private. "
              "An unfinished or failed episode stays in the denominator as unsuccessful.")
UNREADABLE = "This repository could not be read. Check the link and branch. A private repository must give this service access."
EXECUTION_NOTICE = ("Hosted environment execution is not enabled. The commit is frozen and recorded, "
                    "but this service has not run the repository or the challenge environment.")
# Fixed application source. It proves that the protocol never carries a seed.
MECHANISM_POLICY = ("import json, sys\n"
                    "for line in sys.stdin:\n"
                    "    message = json.loads(line)\n"
                    "    if 'seed' in message: sys.exit(1)\n"
                    "    print(json.dumps({'ok': True} if message['type'] == 'reset' else {'action': 0}), flush=True)\n")
MECHANISM_SEEDS = [10, 11, 12, 13]
EXAMPLE_POLICY = '''"""Example policy. Replace the constant action with your frozen model."""
import json
import sys

for line in sys.stdin:
    message = json.loads(line)
    if message["type"] == "reset":
        reply = {"ok": True}  # Clear any per-episode memory here.
    else:
        reply = {"action": 0}  # Choose an action from message["observation"].
    print(json.dumps(reply), flush=True)
'''


class MechanismEnvironment:
    """A deterministic test environment for the seed, protocol, and scoring path."""

    def reset(self, seed=None):
        self.seed, self.steps = seed, 0
        return {"step": 0}, {}

    def step(self, action):
        self.steps += 1
        done = self.steps >= 3
        return {"step": self.steps}, 1.0, done, False, {"success": done and action == 0 and self.seed % 2 == 0}


def mechanism_test():
    """Run a constant policy through the real harness and scorer. Raise if the result is wrong."""
    rows = harness.run_episodes(MechanismEnvironment, [sys.executable, "-I", "-c", MECHANISM_POLICY], MECHANISM_SEEDS, step_seconds=10)
    text = harness.rows_to_csv(rows)
    measured = harness.score_episodes(text, MECHANISM_SEEDS)
    if measured["success_rate"] != 0.5 or measured["mean_score"] != 3.0 or measured["completed_episodes"] != len(MECHANISM_SEEDS):
        raise ValueError("The environment scorer failed its known-answer check.")
    try:
        harness.score_episodes(text, MECHANISM_SEEDS[:-1])
    except ValueError:
        pass
    else:
        raise ValueError("The environment scorer accepted results for the wrong seeds.")
    return {"kind": "environment_mechanism_test", "metric": "success_rate", "score": measured["success_rate"],
            "rows": measured["episodes"], "mean_score": measured["mean_score"]}


def _count(value, name, minimum=1, maximum=100000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be a whole number from {minimum:,} to {maximum:,}.")
    return value


def validate_policy(values):
    start, end = values.get("reserved_start"), values.get("reserved_end")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= SEED_LIMIT:
        raise ValueError("Enter a reserved seed range with a start below its end.")
    development = _count(values.get("development_seeds"), "Development seeds")
    final = _count(values.get("final_seeds"), "Final seeds")
    smoke = _count(values.get("smoke_seeds", 3), "Smoke-test seeds", maximum=50)
    if end - start + 1 < MIN_RANGE_MULTIPLE * (development + final):
        raise ValueError(f"The reserved range must hold at least {MIN_RANGE_MULTIPLE} times the evaluation seeds, so the chosen seeds cannot be guessed.")
    if start < smoke and SEED_LIMIT - end < smoke:
        raise ValueError("Leave room outside the reserved range for the public smoke-test seeds.")
    factory = values.get("env_factory")
    if not isinstance(factory, str) or not re.fullmatch(r"[A-Za-z_][\w.]*:[A-Za-z_]\w*", factory) or len(factory) > 200:
        raise ValueError("Enter the environment factory as module:function.")
    metric = values.get("primary_metric")
    if metric not in METRICS:
        raise ValueError("Choose success_rate or mean_score as the primary metric.")
    steps = values.get("max_episode_steps")
    if steps is not None:
        _count(steps, "The episode step limit", maximum=10 ** 12)
    hours = values.get("evaluation_hours")
    if hours is not None and (isinstance(hours, bool) or not isinstance(hours, (int, float)) or not 0 < hours <= 8760):
        raise ValueError("Evaluation hours must be a positive number.")
    return {"reserved_start": start, "reserved_end": end, "development_seeds": development, "final_seeds": final, "smoke_seeds": smoke,
            "env_factory": factory, "primary_metric": metric, "max_episode_steps": steps, "evaluation_hours": hours}


def _read(url, limit=1024 * 1024):
    try:
        return sources.github_fetch(url, limit)[0]
    except ValueError as exc:
        if "readable" in str(exc):
            raise ValueError(UNREADABLE) from exc
        if "denied access" in str(exc):
            raise ValueError("GitHub denied access or reached its rate limit. Retry later. A private repository must give this service access.") from exc
        raise


def _resolve(url, ref=""):
    """Turn a repository link and optional ref into one fixed commit."""
    owner, repo = sources.parse_repository(url)
    if ref and (len(ref) > 200 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", ref) or ".." in ref):
        raise ValueError("Enter a valid branch, tag, or commit.")
    api = f"https://api.github.com/repos/{owner}/{repo}"
    metadata = json.loads(_read(api))
    target = ref or metadata["default_branch"]
    commit = json.loads(_read(api + "/commits/" + quote(target, safe="")))["sha"]
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("The repository did not provide a fixed commit.")
    return owner, repo, commit, (metadata.get("license") or {}).get("spdx_id"), bool(metadata.get("private"))


def configure(project, values):
    """Validate the seed policy and pin the environment source before saving either."""
    clean = validate_policy(values)
    ref = values.get("env_ref") or ""
    owner, repo, commit, license_id, private = _resolve(values.get("env_repository") or "", ref)
    project["environment"] = {**clean, "env_repository": f"https://github.com/{owner}/{repo}", "env_ref": ref, "env_commit": commit, "env_license": license_id, "env_private": private}
    return copy.deepcopy(project["environment"])


def smoke_seeds(config):
    """Public seeds for local checks. They always sit outside the reserved range."""
    count = config["smoke_seeds"]
    first = 0 if config["reserved_start"] >= count else config["reserved_end"] + 1
    return list(range(first, first + count))


def evaluation_seeds(project, config):
    """Choose hidden seeds deterministically for one challenge definition."""
    identity = json.dumps([project["_seed"], config["env_repository"], config["env_commit"], config["reserved_start"], config["reserved_end"]])
    generator = random.Random(hashlib.sha256(identity.encode()).hexdigest())
    chosen = generator.sample(range(config["reserved_start"], config["reserved_end"] + 1), config["development_seeds"] + config["final_seeds"])
    return {"development": sorted(chosen[:config["development_seeds"]]), "final": sorted(chosen[config["development_seeds"]:])}


def commitment(seeds):
    """Publish this hash now and audit the seed list after final scoring."""
    return hashlib.sha256(json.dumps(seeds, sort_keys=True).encode()).hexdigest()


def public_seed_policy(config, seeds):
    return {"unit": "seed", "method": "reserved_seed_range", "rules": SEED_RULES,
            "training": "Any seed outside the reserved range.",
            "reserved_range": [config["reserved_start"], config["reserved_end"]],
            "smoke_seeds": smoke_seeds(config), "development_seeds": config["development_seeds"], "final_seeds": config["final_seeds"],
            "membership": "Exact evaluation seeds and their development or final assignment stay private.",
            "commitment_sha256": commitment(seeds)}


def _relative(path, name):
    if not isinstance(path, str) or not path or len(path) > 300 or path.startswith("/") or "\\" in path or any(part in {"", ".", ".."} for part in path.split("/")):
        raise ValueError(f"The manifest {name} must be a relative path inside the repository.")
    return path


def validate_manifest(text):
    try:
        manifest = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"{MANIFEST} is not valid JSON.") from exc
    allowed = {"format", "policy_command", "requirements", "checkpoint", "framework"}
    if not isinstance(manifest, dict) or set(manifest) - allowed or manifest.get("format") != MANIFEST_FORMAT:
        raise ValueError(f"{MANIFEST} must use format {MANIFEST_FORMAT} and only its documented fields.")
    command = manifest.get("policy_command")
    if not isinstance(command, list) or not 1 <= len(command) <= 32 or any(not isinstance(part, str) or not part or len(part) > 300 for part in command):
        raise ValueError("The manifest policy_command must be a list of arguments. It is never run through a shell.")
    paths = []
    if "requirements" in manifest:
        paths.append(_relative(manifest["requirements"], "requirements"))
    checkpoint = manifest.get("checkpoint")
    if checkpoint is not None:
        if not isinstance(checkpoint, dict) or set(checkpoint) - {"path", "url", "sha256"} or ("path" in checkpoint) == ("url" in checkpoint):
            raise ValueError("The manifest checkpoint needs one path or one url, plus sha256.")
        if not re.fullmatch(r"[a-f0-9]{64}", str(checkpoint.get("sha256"))):
            raise ValueError("The manifest checkpoint needs a lowercase SHA-256 hash.")
        if "path" in checkpoint:
            paths.append(_relative(checkpoint["path"], "checkpoint path"))
        else:
            sources.source_syntax(checkpoint["url"])
    if "framework" in manifest and (not isinstance(manifest["framework"], str) or len(manifest["framework"]) > 100):
        raise ValueError("The manifest framework must be short text.")
    return manifest, paths


def freeze_submission(repository_url, ref=""):
    """Pin a repository commit and check its manifest. Nothing from it is executed."""
    owner, repo, commit, license_id, private = _resolve(repository_url, ref)
    # Only the API accepts the service credential. Without one, public files come from the raw host.
    location = (f"https://api.github.com/repos/{owner}/{repo}/contents/{MANIFEST}?ref={commit}" if sources.github_token()
                else f"https://raw.githubusercontent.com/{owner}/{repo}/{commit}/{MANIFEST}")
    try:
        body = sources.github_fetch(location, 64 * 1024, raw=True)[0]
    except ValueError as exc:
        if "readable" in str(exc):
            raise ValueError(f"Add {MANIFEST} to the repository root at this commit, then submit again.") from exc
        raise
    manifest, paths = validate_manifest(body.decode("utf-8", errors="replace"))
    tree = json.loads(_read(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{commit}?recursive=1", 2 * 1024 * 1024))
    files = {entry["path"] for entry in tree.get("tree", []) if entry.get("type") == "blob"}
    if not tree.get("truncated"):
        missing = [path for path in paths if path not in files]
        if missing:
            raise ValueError("The repository commit does not contain: " + ", ".join(missing))
    return {"repository": f"https://github.com/{owner}/{repo}", "commit": commit, "license": license_id, "private": private,
            "manifest": manifest, "manifest_sha256": hashlib.sha256(body).hexdigest()}


def write_package(public, private, spec, config, seeds):
    """Write participant files and the private seed list for one build."""
    public.joinpath("environment_harness.py").write_text(Path(harness.__file__).read_text())
    public.joinpath("example_policy.py").write_text(EXAMPLE_POLICY)
    public.joinpath("autokaggle-submission.example.json").write_text(json.dumps({
        "format": MANIFEST_FORMAT, "policy_command": ["python", "example_policy.py"], "requirements": "requirements.lock",
        "checkpoint": {"path": "model.pt", "sha256": "0" * 64}, "framework": "pytorch"}, indent=2) + "\n")
    if seeds:
        private.joinpath("seeds.json").write_text(json.dumps(seeds, sort_keys=True, indent=2) + "\n")

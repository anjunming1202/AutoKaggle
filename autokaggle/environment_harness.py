"""Run a frozen policy in a trusted environment over fixed seeds, then score the episodes.

This file uses the Python standard library only and is copied into research packages.
The harness owns the environment and the seeds. The policy runs in a separate process
and receives observations through a local protocol; it never receives a seed.
This harness does not sandbox the policy. Run submitted code only inside an isolated runner.
"""
import argparse
import csv
import importlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

PROTOCOL = "autokaggle.policy-protocol.v1"
METRIC_VERSION = "autokaggle.environment-metrics.v1"
EPISODE_COLUMNS = ["seed", "status", "success", "score", "steps"]
STATUSES = {"completed", "step_limit", "time_limit", "policy_error"}
MAX_RESPONSE = 1024 * 1024


class PolicyFailure(RuntimeError):
    """The policy process stopped, timed out, or broke the protocol."""


def _plain(value):
    for name in ("tolist", "item"):
        if hasattr(value, name):
            return getattr(value, name)()
    raise TypeError("The observation cannot be sent to the policy.")


class Policy:
    """One policy process. A watchdog bounds every read and write."""

    def __init__(self, command, cwd=None, step_seconds=60):
        self.step_seconds = step_seconds
        self.deadline = None
        environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(cwd or Path.cwd()), "PYTHONUNBUFFERED": "1"}
        self.process = subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._stop = threading.Event()
        threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self):
        while not self._stop.wait(0.2):
            if self.deadline is not None and time.monotonic() > self.deadline:
                self.process.kill()
                return

    def ask(self, message):
        self.deadline = time.monotonic() + self.step_seconds
        try:
            self.process.stdin.write(json.dumps(message, default=_plain, allow_nan=False).encode() + b"\n")
            self.process.stdin.flush()
            line = self.process.stdout.readline(MAX_RESPONSE + 1)
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise PolicyFailure("The policy process stopped.") from exc
        finally:
            self.deadline = None
        if not line or len(line) > MAX_RESPONSE or not line.endswith(b"\n"):
            raise PolicyFailure("The policy process stopped or sent an invalid response.")
        try:
            response = json.loads(line)
        except ValueError as exc:
            raise PolicyFailure("The policy sent invalid JSON.") from exc
        if not isinstance(response, dict):
            raise PolicyFailure("The policy sent an invalid response.")
        return response

    def close(self):
        self._stop.set()
        for stream in (self.process.stdin, self.process.stdout):
            try:
                stream.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


def _row(seed, status, success=False, score=0.0, steps=0):
    return {"seed": seed, "status": status, "success": int(bool(success)), "score": float(score), "steps": steps}


def _episode(environment, policy, seed, max_steps, stop_at):
    observation, _ = environment.reset(seed=seed)
    policy.ask({"type": "reset", "protocol": PROTOCOL})
    score, steps = 0.0, 0
    while True:
        response = policy.ask({"type": "act", "observation": observation})
        if "action" not in response:
            raise PolicyFailure("The policy response has no action.")
        try:
            observation, reward, terminated, truncated, info = environment.step(response["action"])
        except (TypeError, ValueError, KeyError, IndexError) as exc:
            raise PolicyFailure("The environment rejected the action.") from exc
        score += float(reward)
        steps += 1
        if terminated or truncated:
            return _row(seed, "completed", (info or {}).get("success"), score, steps)
        if max_steps and steps >= max_steps:
            return _row(seed, "step_limit", False, score, steps)
        if stop_at is not None and time.monotonic() > stop_at:
            return _row(seed, "time_limit", False, score, steps)


def run_episodes(make_environment, command, seeds, *, max_steps=None, step_seconds=60, total_seconds=None, cwd=None):
    """Return one row per seed. A policy failure scores zero for that seed and all later seeds."""
    stop_at = time.monotonic() + total_seconds if total_seconds else None
    environment = make_environment()
    policy = Policy(command, cwd=cwd, step_seconds=step_seconds)
    rows, failed = [], False
    try:
        for seed in seeds:
            if failed:
                rows.append(_row(seed, "policy_error"))
            elif stop_at is not None and time.monotonic() > stop_at:
                rows.append(_row(seed, "time_limit"))
            else:
                try:
                    rows.append(_episode(environment, policy, seed, max_steps, stop_at))
                except PolicyFailure:
                    failed = True
                    rows.append(_row(seed, "policy_error"))
    finally:
        policy.close()
        if hasattr(environment, "close"):
            environment.close()
    return rows


def rows_to_csv(rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, EPISODE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _parse(text):
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames != EPISODE_COLUMNS:
        raise ValueError("Episode results must have the columns: " + ",".join(EPISODE_COLUMNS))
    rows = []
    for row in reader:
        if None in row or None in row.values():
            raise ValueError("Each episode row must have one value per column.")
        rows.append(row)
    return rows


def score_episodes(text, expected_seeds):
    """Score one row per expected seed. Unfinished episodes stay in the denominator as unsuccessful."""
    rows = _parse(text)
    seeds, successes, scores, completed = [], 0, [], 0
    for row in rows:
        try:
            seed, success, score, steps = int(row["seed"]), int(row["success"]), float(row["score"]), int(row["steps"])
        except ValueError as exc:
            raise ValueError("Episode values must be numbers.") from exc
        if row["status"] not in STATUSES:
            raise ValueError("An episode has an unknown status.")
        if success not in {0, 1} or steps < 0 or not math.isfinite(score):
            raise ValueError("An episode has an invalid success, score, or step count.")
        if success and row["status"] != "completed":
            raise ValueError("Only a completed episode can count as a success.")
        seeds.append(seed)
        successes += success
        scores.append(score)
        completed += row["status"] == "completed"
    if len(seeds) != len(set(seeds)) or set(seeds) != set(expected_seeds):
        raise ValueError("Episode results must contain exactly one row for each evaluation seed.")
    episodes = len(seeds)
    rate = successes / episodes
    # A Wilson interval stays meaningful when no episode succeeds.
    z, denominator = 1.96, 1 + 1.96 ** 2 / episodes
    center = (rate + z ** 2 / (2 * episodes)) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / episodes + z ** 2 / (4 * episodes ** 2)) / denominator
    return {"metric_version": METRIC_VERSION, "episodes": episodes, "completed_episodes": completed, "success_rate": rate,
            "success_interval_95": [max(0.0, center - margin), min(1.0, center + margin)], "mean_score": sum(scores) / episodes}


def _factory(name):
    module, function = name.split(":", 1)
    return getattr(importlib.import_module(module), function)


def _seeds(value):
    return [int(part) for part in value.split(",") if part.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run a policy over fixed seeds and write episode results.")
    run.add_argument("--env-factory", required=True, help="module:callable that returns a Gymnasium-style environment")
    run.add_argument("--env-path", default=".", help="Directory that contains the environment module")
    run.add_argument("--seeds", required=True, type=_seeds, help="Comma-separated seeds")
    run.add_argument("--output", default="episodes.csv")
    run.add_argument("--max-steps", type=int)
    run.add_argument("--step-seconds", type=float, default=60)
    run.add_argument("--total-seconds", type=float)
    run.add_argument("--policy-cwd", default=".")
    run.add_argument("policy", nargs="+", help="Policy command after --")
    score = commands.add_parser("score", help="Score episode results against the expected seeds.")
    score.add_argument("--episodes", default="episodes.csv")
    score.add_argument("--seeds", required=True, type=_seeds)
    arguments = parser.parse_args()
    if arguments.command == "run":
        sys.path.insert(0, arguments.env_path)
        rows = run_episodes(_factory(arguments.env_factory), arguments.policy, arguments.seeds, max_steps=arguments.max_steps,
                            step_seconds=arguments.step_seconds, total_seconds=arguments.total_seconds, cwd=arguments.policy_cwd)
        Path(arguments.output).write_text(rows_to_csv(rows))
        print(json.dumps(score_episodes(rows_to_csv(rows), arguments.seeds), indent=2))
    else:
        print(json.dumps(score_episodes(Path(arguments.episodes).read_text(), arguments.seeds), indent=2))


if __name__ == "__main__":
    main()

"""Pinned SKILL-KD algorithm with a Pi/Docker benchmark adapter.

No upstream prompts, rule operations, acceptance criteria, or edit history are
rewritten. The two boundaries are task execution and OpenAI-compatible I/O.
Run through sst skill-kd, not by invoking this file with arbitrary paths.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace

from openai.types.chat import ChatCompletionMessage
from pact import run_experiment as upstream
from pact.llm import LLMClient, LLMConfig, merge_usage
from pact.skill import EditRecord, SkillState
from pact.skill_ops import canonicalize_skill_text, parse_skill_rules, render_for_agent

SEED = """[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.
why: Generic starting point without family-specific knowledge.
"""


def digest(value):
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp-{os.getpid()}")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def agent_package(family, rules):
    # `why` and edit-log provenance stay private, exactly as in upstream.
    body = render_for_agent(parse_skill_rules(canonicalize_skill_text(rules)))
    return (f"---\nname: {family}\ndescription: Reusable instructions for {family} tasks.\n---\n\n"
            f"# {family}\n\n{body}")


class FamilyAdapter:
    name = "sst"

    def __init__(self, request):
        self.request = request

    def render_task(self, task, output_dir=None):
        return self.request["publicTask"]

    def critic_attachments(self, task):
        return None

    def evaluate(self, task, final_answer, judge=None, trajectory=None, output_dir=None):
        return trajectory["evaluation"]


class PiRollouts:
    def __init__(self, request):
        self.request = request

    def __call__(self, llm, adapter, role, task, skill_text, output_dir=None, gold_path=""):
        if role not in {"student", "student_retry", "teacher"}:
            raise ValueError(f"Unsupported rollout role: {role}")
        root = Path(output_dir)
        package = root / "skill" / self.request["family"]
        package.mkdir(parents=True, exist_ok=True)
        skill_md = agent_package(self.request["family"], skill_text)
        package_file = package / "SKILL.md"
        if package_file.exists() and package_file.read_text(encoding="utf-8") != skill_md:
            raise ValueError(f"Cached rollout Skill changed: {root}")
        package_file.write_text(skill_md, encoding="utf-8")
        wire = {
            "configPath": self.request["configPath"], "family": self.request["family"],
            "train": self.request["train"], "role": role,
            "packageRoot": str(package), "outputRoot": str(root),
            "fingerprint": digest([self.request["fingerprint"], role, skill_md, str(root)]),
        }
        response_file = root / "response.json"
        if not response_file.exists():
            request_file = root / "request.json"
            write_json(request_file, wire)
            # A new TS process creates a new Pi session and Docker environment.
            command = self.request["rolloutCommand"] + [str(request_file)]
            with (root / "stdout.log").open("a") as stdout, (root / "stderr.log").open("a") as stderr:
                child = subprocess.Popen(command, cwd=self.request["projectRoot"], stdout=stdout, stderr=stderr)
                previous = {}

                def stop(signum, frame):
                    child.send_signal(signal.SIGTERM)
                    try:
                        child.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
                    raise SystemExit(128 + signum)

                for sig in (signal.SIGTERM, signal.SIGINT):
                    previous[sig] = signal.signal(sig, stop)
                try:
                    code = child.wait()
                finally:
                    for sig, handler in previous.items():
                        signal.signal(sig, handler)
                if code != 0:
                    raise RuntimeError(f"Pi {role} exited {code}; inspect {root / 'stderr.log'}")
        response = read_json(response_file)
        if response["fingerprint"] != wire["fingerprint"]:
            raise ValueError(f"Rollout cache fingerprint mismatch: {root}")
        raw_file = Path(response["rawSessionFile"])
        if digest(raw_file.read_text(encoding="utf-8")) != response["rawSessionSha256"]:
            raise ValueError(f"Raw trajectory changed: {raw_file}")
        if digest(response["raw"]) != response["rawSessionSha256"]:
            raise ValueError(f"Cached trajectory changed: {response_file}")
        response["skill_used"] = render_for_agent(parse_skill_rules(canonicalize_skill_text(skill_text)))
        print(f"[skill-kd/{self.request['family']}] {role}: score={response['evaluation']['score']}", flush=True)
        return response


def collect_stream(stream):
    """Assemble streaming reasoning, tool-call fragments and final usage."""
    content, reasoning, calls = [], [], {}
    usage = None
    finish = None
    with stream:
        for chunk in stream:
            if chunk.usage is not None:
                usage = chunk.usage.model_dump()
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            finish = choice.finish_reason or finish
            delta = choice.delta
            if delta.content:
                content.append(delta.content)
            if getattr(delta, "reasoning_content", None):
                reasoning.append(delta.reasoning_content)
            for fragment in delta.tool_calls or []:
                call = calls.setdefault(fragment.index, {"id": "", "type": "function",
                    "function": {"name": "", "arguments": ""}})
                if fragment.id:
                    call["id"] = fragment.id
                if fragment.function:
                    call["function"]["name"] += fragment.function.name or ""
                    call["function"]["arguments"] += fragment.function.arguments or ""
    message = {"role": "assistant", "content": "".join(content), "reasoning_content": "".join(reasoning)}
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    return {"message": message, "usage": usage, "finish_reason": finish}


class StreamingCritic(LLMClient):
    """Upstream client contract, with streaming, token cap and durable call cache.

    Qwen thinking mode accepts auto tool choice. For the upstream forced final
    turn we expose only the requested terminator with auto choice; the upstream
    tool loop still enforces its terminator and hard turn cap. This wire-level
    compatibility choice is recorded alongside every response.
    """

    def __init__(self, request):
        super().__init__(LLMConfig(model=request["teacherModel"],
            base_url=os.environ["SKILL_KD_BASE_URL"], api_key_env="SKILL_KD_API_KEY",
            enable_thinking=True, timeout=600, max_retries=10))
        self.request = request
        self.root = Path(request["outDir"]) / "critic_calls"
        self.group = 0
        self.call = 0
        self.reasoning_by_message = {}

    def start_group(self, index):
        self.group = index
        self.call = 0

    @staticmethod
    def message_key(message):
        return digest({k: message[k] for k in ("role", "content", "tool_calls") if k in message})

    def chat_raw(self, messages, *, tools=None, tool_choice=None, **kwargs):
        self.call += 1
        outgoing = [dict(m) for m in messages]
        for message in outgoing:
            saved = self.reasoning_by_message.get(self.message_key(message))
            if saved:
                message["reasoning_content"] = saved
        effective_tools, effective_choice = tools, tool_choice
        if isinstance(tool_choice, dict):
            name = tool_choice["function"]["name"]
            effective_tools = [t for t in tools if t["function"]["name"] == name]
            if not effective_tools:
                raise ValueError(f"Unknown forced tool: {name}")
            effective_choice = "auto"
        body = {
            "model": self.config.model, "messages": outgoing, "tools": effective_tools,
            "tool_choice": effective_choice, "extra_body": {"enable_thinking": True},
            "max_completion_tokens": self.request["maxCompletionTokens"],
            "stream": True, "stream_options": {"include_usage": True},
        }
        fingerprint = digest([self.request["fingerprint"], body, tool_choice])
        file = self.root / f"group-{self.group:04d}-call-{self.call:04d}.json"
        if file.exists():
            record = read_json(file)
            if record["fingerprint"] != fingerprint:
                raise ValueError(f"Critic cache fingerprint mismatch: {file}")
        else:
            write_json(file.with_suffix(".request.json"), {
                "fingerprint": fingerprint, "requestedToolChoice": tool_choice, "body": body,
            })
            # Upstream handles transient errors when opening the stream. A
            # mid-stream error fails this group and is retried on resume.
            # Mark such attempts explicitly; missing provider usage is unknown.
            attempt = file.with_suffix(".attempts.jsonl")
            attempt.parent.mkdir(parents=True, exist_ok=True)
            with attempt.open("a") as log:
                log.write(json.dumps({"event": "started", "pid": os.getpid()}) + "\n")
            try:
                response = collect_stream(self._call_with_retry(**body))
            except Exception as exc:
                with attempt.open("a") as log:
                    log.write(json.dumps({"event": "failed", "type": type(exc).__name__, "usage_known": False}) + "\n")
                raise
            record = {"fingerprint": fingerprint, **response}
            write_json(file, record)
            with attempt.open("a") as log:
                log.write(json.dumps({"event": "completed"}) + "\n")
        if record["finish_reason"] not in {"stop", "tool_calls"}:
            raise RuntimeError(f"Incomplete critic completion ({record['finish_reason']}); inspect {file}")
        usage = record.get("usage")
        if not usage or usage.get("prompt_tokens") is None or usage.get("completion_tokens") is None:
            raise RuntimeError(f"Provider omitted critic usage; inspect {file}")
        self.total_usage.input_tokens += usage["prompt_tokens"]
        self.total_usage.output_tokens += usage["completion_tokens"]
        self.total_usage.cached_tokens += (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        self.total_usage.requests += 1
        message = record["message"]
        self.reasoning_by_message[self.message_key(message)] = message.get("reasoning_content", "")
        return ChatCompletionMessage.model_validate(message)


def check_group(summary, group_dir):
    if summary.get("failed") or summary.get("error"):
        raise RuntimeError(f"Acquisition incomplete: {summary.get('error')}; inspect {group_dir}")
    for file in group_dir.glob("round_*/critic.json"):
        critic = read_json(file)
        if critic.get("loop_error"):
            # Upstream otherwise turns a failed tool loop into an empty edit.
            # Do not label infrastructure/protocol failure as completed learning.
            raise RuntimeError(f"Critic loop incomplete: {critic['loop_error']}; inspect {file}")


def audit_usage(root, student_model, teacher_model):
    """Count persisted API usage once, including abandoned Pi attempts.

    Group summaries count logical algorithm execution (cache replay included).
    This separate ledger counts saved physical calls; a failed stream without
    usage is unknown, never silently assumed free.
    """
    totals, sessions, incomplete = {}, [], []
    outputs = []
    for group in (root / "evolution/groups").glob("*"):
        outputs.extend([(group / "student_initial_outputs", "student"), (group / "teacher_outputs", "teacher")])
        outputs.extend((d / "student_retry_outputs", "student") for d in group.glob("round_*") if d.is_dir())
    for output, role in outputs:
        for attempt in (output / "attempts").glob("*"):
            files = list((attempt / "train-solvers/iteration-1/session").glob("*.jsonl"))
            if not files:
                incomplete.append({"path": str(attempt), "reason": "no persisted solver session"})
            for file in files:
                usage = dict(model=teacher_model if role == "teacher" else student_model,
                             input_tokens=0, output_tokens=0, cached_tokens=0, requests=0)
                for line in file.read_text(encoding="utf-8").splitlines():
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        incomplete.append({"path": str(file), "reason": "incomplete session line"})
                        continue
                    msg = record.get("message", {}) if record.get("type") == "message" else {}
                    u = msg.get("usage") if msg.get("role") == "assistant" else None
                    if u:
                        usage["input_tokens"] += u.get("input", 0) + u.get("cacheRead", 0) + u.get("cacheWrite", 0)
                        usage["output_tokens"] += u.get("output", 0)
                        usage["cached_tokens"] += u.get("cacheRead", 0)
                        usage["requests"] += 1
                totals[role] = merge_usage(totals.get(role), usage)
                sessions.append({"role": role, "file": str(file), "sha256": digest(file.read_text(encoding="utf-8")), "usage": usage})
            if not (attempt / "result.json").exists():
                incomplete.append({"path": str(attempt), "reason": "solver did not finish; in-flight API usage may be missing"})
    for file in (root / "critic_calls").glob("group-*-call-*.json"):
        if file.name.endswith(".request.json"):
            continue
        record = read_json(file)
        u = record.get("usage")
        if u:
            usage = dict(model=teacher_model, input_tokens=u["prompt_tokens"], output_tokens=u["completion_tokens"],
                         cached_tokens=(u.get("prompt_tokens_details") or {}).get("cached_tokens", 0), requests=1)
            totals["critic"] = merge_usage(totals.get("critic"), usage)
        else:
            incomplete.append({"path": str(file), "reason": "critic usage missing"})
    for file in (root / "critic_calls").glob("*.attempts.jsonl"):
        events = [json.loads(line) for line in file.read_text().splitlines()]
        if sum(e["event"] == "started" for e in events) > sum(e["event"] == "completed" for e in events):
            incomplete.append({"path": str(file), "reason": "interrupted/failed critic request without complete usage"})
    return {"recordedPhysicalUsage": totals, "solverSessions": sessions, "incompleteAttempts": incomplete,
            "measurement": "Provider-reported tokens; unreported in-flight/retried requests may add billed usage."}


def evolve(request, critic=None, rollout=None):
    root = Path(request["outDir"])
    root.mkdir(parents=True, exist_ok=True)
    checkpoint_file = root / "checkpoint.json"
    current = canonicalize_skill_text(SEED)
    skill = SkillState(original=current, current=current)
    groups = []
    if checkpoint_file.exists():
        saved = read_json(checkpoint_file)
        if saved["fingerprint"] != request["fingerprint"]:
            raise ValueError("Checkpoint fingerprint mismatch")
        skill.current, skill.version = saved["skill"], saved["version"]
        parse_skill_rules(skill.current)
        skill.edit_log = [EditRecord.from_dict(r) for r in saved["editLog"]]
        groups = saved["groups"]
    if len(groups) > request["anchorPasses"]:
        raise ValueError("Checkpoint has too many anchor visits")
    task = {"id": f"{request['family']}-{request['train']}", "question": request["publicTask"]}
    for index, group in enumerate(groups):
        directory = root / "evolution" / "groups" / f"{index:04d}_{upstream.safe_id(task)}"
        if read_json(directory / "summary.json") != group:
            raise ValueError(f"Completed group summary changed: {directory}")
        check_group(group, directory)
    adapter = FamilyAdapter(request)
    critic = critic or StreamingCritic(request)
    previous_rollout = upstream.run_rollout
    upstream.run_rollout = rollout or PiRollouts(request)
    try:
        for index in range(len(groups), request["anchorPasses"]):
            critic.start_group(index)
            summary = upstream.evolve_on_task(
                adapter=adapter, task=task, task_index=index, total_tasks=request["anchorPasses"],
                skill=skill, student=SimpleNamespace(), teacher=SimpleNamespace(), critic=critic,
                judge=None, out_dir=root, max_iters=request["maxAdaptiveRounds"],
                skip_self_evolution_if_teacher_fails=False,
            )
            directory = root / "evolution" / "groups" / f"{index:04d}_{upstream.safe_id(task)}"
            check_group(summary, directory)
            groups.append(summary)
            write_json(checkpoint_file, {
                "fingerprint": request["fingerprint"], "skill": skill.current, "version": skill.version,
                "editLog": [r.to_dict() for r in skill.edit_log], "groups": groups,
            })
    finally:
        upstream.run_rollout = previous_rollout
    usage = {}
    for group in groups:
        for role, amount in group.get("usage", {}).items():
            usage[role] = merge_usage(usage.get(role), amount)
    final = {
        "fingerprint": request["fingerprint"], "upstreamCommit": request["upstreamCommit"],
        "skillVersion": skill.version, "anchorPasses": len(groups),
        "maxAdaptiveRounds": request["maxAdaptiveRounds"], "groups": groups, "usage": usage,
        "rules": skill.current, "skillMarkdown": agent_package(request["family"], skill.current),
    }
    write_json(root / "complete.json", final)
    return final


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: bridge.py request.json")
    request = read_json(sys.argv[1])
    try:
        evolve(request)
    finally:
        write_json(Path(request["outDir"]) / "usage-audit.json", audit_usage(
            Path(request["outDir"]), request["studentModel"], request["teacherModel"]))

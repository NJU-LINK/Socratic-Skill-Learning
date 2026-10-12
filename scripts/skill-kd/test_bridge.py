"""Offline integration tests run the actual pinned upstream evolution loop."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from openai.types.chat import ChatCompletionMessage, ChatCompletionChunk
from bridge import (SEED, PiRollouts, StreamingCritic, agent_package, audit_usage, collect_stream,
                    digest, evolve, read_json, write_json)
from pact.skill_ops import canonicalize_skill_text


def op(content):
    return {"op": "add", "rule": {"title": content, "content": content, "why": "PRIVATE EXPLANATION"}}


class Critic:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.prompts = []
        self.calls = 0

    def start_group(self, index):
        pass

    def get_usage(self):
        return dict(model="teacher", input_tokens=10*self.calls, output_tokens=2*self.calls,
                    cached_tokens=0, requests=self.calls)

    def chat_raw(self, messages, **kwargs):
        self.calls += 1
        self.prompts.append(json.dumps(messages))
        answer = next(self.answers)
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, tuple):
            name, arguments = answer
        else:
            name, arguments = "submit_ops", {"ops": answer}
        return ChatCompletionMessage.model_validate({"role": "assistant", "content": "considering evidence",
            "tool_calls": [{"id": f"call-{self.calls}", "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)}}]})


class Rollouts:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []

    def __call__(self, llm, adapter, role, task, skill_text, **kwargs):
        self.calls.append((role, skill_text))
        success = next(self.outcomes)
        if isinstance(success, Exception):
            raise success
        return {"raw": f"FULL_RAW_{role}", "final_answer": "done", "skill_used": skill_text,
                "evaluation": {"success": success, "score": float(success)},
                "usage": dict(model="teacher" if role == "teacher" else "student", input_tokens=100,
                              output_tokens=10, cached_tokens=20, requests=1)}


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.request = dict(family="test-family", train="v01", fingerprint="fixture",
            publicTask="PUBLIC_SPEC_AND_ANCHOR", outDir=str(self.root),
            upstreamCommit="pinned", anchorPasses=1, maxAdaptiveRounds=3,
            configPath="not-used", projectRoot=str(self.root), teacherModel="qwen3.7-max",
            maxCompletionTokens=65536)

    def test_first_try_success_never_calls_teacher_or_critic(self):
        rollout, critic = Rollouts([True]), Critic([])
        result = evolve(self.request, critic, rollout)
        self.assertEqual([role for role, _ in rollout.calls], ["student"])
        self.assertEqual(result["skillVersion"], 0)
        self.assertEqual(critic.calls, 0)
        self.assertEqual(result["usage"]["student"]["requests"], 1)

    def test_failed_candidate_rolls_back_and_teacher_failure_still_teaches(self):
        rollout = Rollouts([False, False, False, True])
        critic = Critic([[op("BAD")], [op("GOOD")]])
        result = evolve(self.request, critic, rollout)
        self.assertEqual([r for r, _ in rollout.calls], ["student", "teacher", "student_retry", "student_retry"])
        self.assertIn("BAD", rollout.calls[2][1])
        self.assertNotIn("BAD", rollout.calls[3][1])
        self.assertIn("GOOD", result["rules"])
        self.assertNotIn("BAD", result["rules"])
        self.assertEqual(result["skillVersion"], 1)
        self.assertNotIn("PRIVATE EXPLANATION", result["skillMarkdown"])
        self.assertIn("FULL_RAW_student", critic.prompts[0])
        self.assertIn("FULL_RAW_teacher", critic.prompts[0])
        self.assertIn("FULL_RAW_student_retry", critic.prompts[1])
        self.assertEqual(result["usage"]["student"]["requests"], 3)
        self.assertEqual(result["usage"]["teacher"]["requests"], 1)
        self.assertEqual(result["usage"]["critic"]["requests"], 2)

    def test_all_failed_candidates_leave_seed_unchanged(self):
        result = evolve(self.request, Critic([[op("A")], [op("B")], [op("C")]]),
                        Rollouts([False, True, False, False, False]))
        self.assertEqual(result["rules"], canonicalize_skill_text(SEED))
        self.assertEqual(result["skillVersion"], 0)
        self.assertFalse(result["groups"][0]["success"])

    def test_empty_ops_skip_retry(self):
        rollout = Rollouts([False, True])
        result = evolve(self.request, Critic([[]]), rollout)
        self.assertEqual(len(rollout.calls), 2)
        self.assertEqual(result["skillVersion"], 0)

    def test_persistent_edit_history_retrieval_uses_real_upstream_artifacts(self):
        self.request["anchorPasses"] = 2
        critic = Critic([[op("LEARNED")], ("get_original_trajectories", {"edit_index": 0}), []])
        result = evolve(self.request, critic, Rollouts([False, True, True, False, True]))
        self.assertEqual(result["skillVersion"], 1)
        tool = json.loads(critic.prompts[2])[-1]
        self.assertEqual(tool["role"], "tool")
        retrieved = json.loads(tool["content"])
        self.assertEqual(retrieved["student_trajectory"]["model_output"], "FULL_RAW_student")
        self.assertEqual(retrieved["teacher_trajectory"]["model_output"], "FULL_RAW_teacher")
        self.assertNotIn("LEARNED", retrieved["student_trajectory"]["skill_used"])
        self.assertEqual(result["anchorPasses"], 2)

    def test_completed_checkpoint_resume_makes_no_new_calls(self):
        first = evolve(self.request, Critic([[op("LEARNED")]]), Rollouts([False, True, True]))
        resumed = evolve(self.request, Critic([]), Rollouts([]))
        self.assertEqual(first, resumed)
        changed = dict(self.request, fingerprint="changed")
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            evolve(changed, Critic([]), Rollouts([]))

    def test_infrastructure_failure_never_writes_completion(self):
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            evolve(self.request, Critic([]), Rollouts([RuntimeError("Docker unavailable")]))
        self.assertFalse((self.root / "complete.json").exists())

    def test_critic_api_failure_is_not_silently_an_empty_edit(self):
        with self.assertRaisesRegex(RuntimeError, "Critic loop incomplete"):
            evolve(self.request, Critic([RuntimeError("HTTP failed")]), Rollouts([False, True]))
        self.assertFalse((self.root / "checkpoint.json").exists())
        self.assertFalse((self.root / "complete.json").exists())

    def test_usage_audit_includes_abandoned_attempts_and_flags_missing_usage(self):
        attempt = self.root / "evolution/groups/0000_test/student_initial_outputs/attempts/abandoned"
        session = attempt / "train-solvers/iteration-1/session/raw.jsonl"
        session.parent.mkdir(parents=True)
        session.write_text(json.dumps({"type": "message", "message": {"role": "assistant",
            "usage": {"input": 100, "output": 10, "cacheRead": 20, "cacheWrite": 0}}}) + "\n")
        critic_dir = self.root / "critic_calls"
        critic_dir.mkdir()
        write_json(critic_dir / "group-0000-call-0001.json", {"usage": {"prompt_tokens": 200,
            "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 50}}})
        (critic_dir / "group-0000-call-0002.attempts.jsonl").write_text('{"event":"started"}\n{"event":"failed"}\n')
        audit = audit_usage(self.root, "student", "teacher")
        self.assertEqual(audit["recordedPhysicalUsage"]["student"]["input_tokens"], 120)
        self.assertEqual(audit["recordedPhysicalUsage"]["critic"]["input_tokens"], 200)
        self.assertEqual(len(audit["incompleteAttempts"]), 2)

    def test_rollout_subprocess_cache_and_raw_session_integrity(self):
        fixture = self.root / "mock_rollout.py"
        fixture.write_text('''import json, pathlib, sys, hashlib
r=json.loads(pathlib.Path(sys.argv[1]).read_text())
root=pathlib.Path(r["outputRoot"])
raw="FULL_UNTRUNCATED_SESSION"
(root/"raw.jsonl").write_text(raw)
(root/"invocations").open("a").write("called\\n")
result=dict(fingerprint=r["fingerprint"], raw=raw, rawSessionFile=str(root/"raw.jsonl"),
 rawSessionSha256=hashlib.sha256(raw.encode()).hexdigest(), final_answer="done",
 evaluation=dict(success=True,score=1))
(root/"response.json").write_text(json.dumps(result))
''')
        self.request["rolloutCommand"] = [sys.executable, str(fixture)]
        runner = PiRollouts(self.request)
        out = self.root / "rollout"
        first = runner(None, None, "teacher", {}, SEED, output_dir=out)
        second = runner(None, None, "teacher", {}, SEED, output_dir=out)
        self.assertEqual(first, second)
        self.assertEqual((out / "invocations").read_text(), "called\n")
        self.assertNotIn("why:", (out / "skill/test-family/SKILL.md").read_text())
        (out / "raw.jsonl").write_text("tampered")
        with self.assertRaisesRegex(ValueError, "trajectory changed"):
            runner(None, None, "teacher", {}, SEED, output_dir=out)


class StreamTest(unittest.TestCase):
    def chunk(self, delta=None, finish=None, usage=None):
        return ChatCompletionChunk.model_validate({"id": "x", "object": "chat.completion.chunk", "created": 0,
            "model": "qwen3.7-max", "choices": [] if delta is None else [{"index": 0, "delta": delta, "finish_reason": finish}],
            "usage": usage})

    def stream(self):
        chunks = [
            self.chunk({"reasoning_content": "reasoning", "content": "done", "tool_calls": [
                {"index": 0, "id": "tc", "type": "function", "function": {"name": "submit_ops", "arguments": '{"ops":'}}]}),
            self.chunk({"tool_calls": [{"index": 0, "function": {"arguments": "[]}"}}]}, "tool_calls"),
            self.chunk(usage={"prompt_tokens": 100, "completion_tokens": 12, "total_tokens": 112,
                              "prompt_tokens_details": {"cached_tokens": 30}}),
        ]
        class Stream:
            def __enter__(self): return iter(chunks)
            def __exit__(self, *args): pass
            def __iter__(self): return iter(chunks)
        return Stream()

    def test_stream_assembly_keeps_reasoning_tool_fragments_and_usage(self):
        result = collect_stream(self.stream())
        self.assertEqual(result["message"]["reasoning_content"], "reasoning")
        self.assertEqual(result["message"]["tool_calls"][0]["function"]["arguments"], '{"ops":[]}')
        self.assertEqual(result["usage"]["prompt_tokens"], 100)

    def test_streaming_critic_cache_forced_tool_and_token_cap(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
            "SKILL_KD_API_KEY": "offline-fixture", "SKILL_KD_BASE_URL": "http://127.0.0.1:1/v1"}):
            request = dict(teacherModel="qwen3.7-max", outDir=root, fingerprint="fixture", maxCompletionTokens=65536)
            critic = StreamingCritic(request)
            messages = [{"role": "user", "content": "test"}]
            tools = [{"type": "function", "function": {"name": "submit_ops"}},
                     {"type": "function", "function": {"name": "get_original_trajectories"}}]
            choice = {"type": "function", "function": {"name": "submit_ops"}}
            with patch.object(critic, "_call_with_retry", return_value=self.stream()) as api:
                message = critic.chat_raw(messages, tools=tools, tool_choice=choice)
                self.assertEqual(message.tool_calls[0].function.name, "submit_ops")
                wire = api.call_args.kwargs
                self.assertEqual(wire["max_completion_tokens"], 65536)
                self.assertTrue(wire["extra_body"]["enable_thinking"])
                self.assertEqual(wire["tool_choice"], "auto")
                self.assertEqual(len(wire["tools"]), 1)
            resumed = StreamingCritic(request)
            with patch.object(resumed, "_call_with_retry", side_effect=AssertionError("must not call network")):
                resumed.chat_raw(messages, tools=tools, tool_choice=choice)
            self.assertEqual(resumed.get_usage()["input_tokens"], 100)
            self.assertEqual(resumed.get_usage()["cached_tokens"], 30)


if __name__ == "__main__":
    unittest.main()

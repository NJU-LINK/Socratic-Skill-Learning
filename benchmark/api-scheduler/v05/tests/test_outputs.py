import copy
import json
from pathlib import Path


APP = Path("/app")


def minute(value):
    hour, minutes = value.split(":")
    return int(hour) * 60 + int(minutes)


def clock(value):
    return f"{value // 60:02d}:{value % 60:02d}"


def load_json(name):
    with (APP / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def inputs():
    data = load_json("tasks.json")
    normal = []
    for index, raw in enumerate(data["tasks"]):
        task = copy.deepcopy(raw)
        task["_index"] = index
        normal.append(task)
    emergencies = []
    for index, raw in enumerate(data.get("emergencies", [])):
        task = copy.deepcopy(raw)
        task["_index"] = index
        emergencies.append(task)
    return data, normal, emergencies


def task_score(task, method):
    urgency = int(task.get("urgency", 0))
    importance = int(task.get("importance", 0))
    if method == "urgency":
        return urgency
    if method == "eisenhower":
        return urgency * importance
    if "team_priority" in task:
        return 5 * urgency + 3 * importance + 2 * int(task["team_priority"])
    return 6 * urgency + 4 * importance


def expected_normal_plan(tasks, start, completed_ids, status, config):
    method = config["priority_method"]
    work_end = minute(config["work_end"])
    completed = set(completed_ids)
    remaining = list(tasks)
    planned = []
    current = start
    while remaining:
        eligible = [
            task for task in remaining
            if set(task.get("depends_on", [])) <= completed
        ]
        if not eligible:
            break
        task = min(
            eligible,
            key=lambda item: (
                -task_score(item, method),
                minute(item["deadline"]) if item.get("deadline") else 10**9,
                item["_index"],
            ),
        )
        remaining.remove(task)
        finish = current + int(task["duration_min"])
        deadline = minute(task["deadline"]) if task.get("deadline") else work_end
        if finish > work_end or finish > deadline:
            continue
        planned.append(
            {
                "task_id": task["id"],
                "title": task["title"],
                "start": clock(current),
                "end": clock(finish),
                "status": status,
            }
        )
        completed.add(task["id"])
        current = finish
    return planned


def expected_schedule():
    data, normal, emergencies = inputs()
    config = data["config"]
    work_end = minute(config["work_end"])
    schedule = expected_normal_plan(
        normal, minute(config["work_start"]), set(), "scheduled", config
    )
    normal_ids = {task["id"] for task in normal}
    for emergency in sorted(
        emergencies, key=lambda item: (minute(item["arrival_time"]), item["_index"])
    ):
        arrival = minute(emergency["arrival_time"])
        preserved = [item for item in schedule if minute(item["end"]) <= arrival]
        completed_normal = {
            item["task_id"] for item in preserved if item["task_id"] in normal_ids
        }
        finish = arrival + int(emergency["duration_min"])
        deadline = minute(emergency["deadline"]) if emergency.get("deadline") else work_end
        if finish <= work_end and finish <= deadline:
            preserved.append(
                {
                    "task_id": emergency["id"],
                    "title": emergency["title"],
                    "start": clock(arrival),
                    "end": clock(finish),
                    "status": "emergency",
                }
            )
            restart_at = finish
        else:
            restart_at = arrival
        remaining = [
            task for task in normal if task["id"] not in completed_normal
        ]
        rebuilt = expected_normal_plan(
            remaining, restart_at, completed_normal, "rescheduled", config
        )
        schedule = sorted(
            preserved + rebuilt, key=lambda item: (item["start"], item["task_id"])
        )
    return schedule


def history():
    entries = []
    with (APP / "history.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                entries.append(json.loads(line))
    return entries


def successful(entries, command):
    return [
        entry for entry in entries
        if entry["request"].get("cmd") == command
        and entry["response"].get("status") == "ok"
    ]


def strip_remote_id(event):
    return {key: value for key, value in event.items() if key != "id"}


def test_output_schema_and_complete_partition():
    data, normal, emergencies = inputs()
    output = load_json("output.json")
    assert set(output) == {"schedule", "completion_summary"}
    assert isinstance(output["schedule"], list)
    summary = output["completion_summary"]
    required = {
        "completed", "missed", "total_tasks", "completed_count", "missed_count"
    }
    assert set(summary) == required
    all_ids = {task["id"] for task in normal + emergencies}
    completed = set(summary["completed"])
    missed = set(summary["missed"])
    assert completed.isdisjoint(missed)
    assert completed | missed == all_ids
    assert summary["total_tasks"] == len(all_ids)
    assert summary["completed_count"] == len(completed)
    assert summary["missed_count"] == len(missed)


def test_completed_and_missed_tasks_match_public_policy():
    output = load_json("output.json")
    expected = expected_schedule()
    actual_ids = [item["task_id"] for item in output["schedule"]]
    expected_ids = [item["task_id"] for item in expected]
    assert actual_ids == expected_ids
    assert output["completion_summary"]["completed"] == sorted(expected_ids)


def test_exact_times_follow_priority_and_replanning_policy():
    output = load_json("output.json")
    expected = expected_schedule()
    assert [
        (item["task_id"], item["start"], item["end"])
        for item in output["schedule"]
    ] == [
        (item["task_id"], item["start"], item["end"])
        for item in expected
    ]


def test_titles_statuses_and_durations_are_exact():
    output = load_json("output.json")
    expected = {item["task_id"]: item for item in expected_schedule()}
    assert len(output["schedule"]) == len(expected)
    for item in output["schedule"]:
        assert set(item) == {"task_id", "title", "start", "end", "status"}
        assert item["title"] == expected[item["task_id"]]["title"]
        assert item["status"] == expected[item["task_id"]]["status"]
        assert minute(item["end"]) > minute(item["start"])


def test_work_hours_deadlines_non_overlap_and_dependencies():
    data, normal, emergencies = inputs()
    output = load_json("output.json")
    by_id = {task["id"]: task for task in normal + emergencies}
    scheduled = {item["task_id"]: item for item in output["schedule"]}
    work_start = minute(data["config"]["work_start"])
    work_end = minute(data["config"]["work_end"])
    previous_end = work_start
    for item in output["schedule"]:
        start = minute(item["start"])
        end = minute(item["end"])
        task = by_id[item["task_id"]]
        assert work_start <= start < end <= work_end
        assert start >= previous_end
        assert end - start == int(task["duration_min"])
        if task.get("deadline"):
            assert end <= minute(task["deadline"])
        for dependency in task.get("depends_on", []):
            assert dependency in scheduled
            assert minute(scheduled[dependency]["end"]) <= start
        previous_end = end


def test_completion_summary_matches_schedule():
    data, normal, emergencies = inputs()
    output = load_json("output.json")
    scheduled_ids = sorted(item["task_id"] for item in output["schedule"])
    all_ids = sorted(task["id"] for task in normal + emergencies)
    summary = output["completion_summary"]
    assert summary["completed"] == scheduled_ids
    assert summary["missed"] == sorted(set(all_ids) - set(scheduled_ids))


def test_final_calendar_state_matches_output():
    output = load_json("output.json")
    state = load_json("/tmp/calendar_state.json")
    remote = sorted(
        (strip_remote_id(item) for item in state.get("events", {}).values()),
        key=lambda item: (item["start"], item["task_id"]),
    )
    assert remote == output["schedule"]


def test_history_has_valid_calendar_requests_and_responses():
    data, _, _ = inputs()
    entries = history()
    assert entries
    for entry in entries:
        assert set(entry) == {"request", "response"}
        assert entry["request"].get("calendar_id") == data["config"]["calendar_id"]
        assert entry["response"].get("status") in {"ok", "error"}
    first_successful_mutation = next(
        entry for entry in entries
        if entry["response"].get("status") == "ok"
        and entry["request"].get("cmd") in {"clear", "insert", "batch_insert", "delete"}
    )
    assert first_successful_mutation["request"]["cmd"] == "clear"
    assert successful(entries, "list")


def test_history_replays_to_the_real_calendar_state():
    entries = history()
    events = {}
    next_id = 0
    for entry in entries:
        request = entry["request"]
        response = entry["response"]
        if response.get("status") != "ok":
            continue
        command = request.get("cmd")
        if command == "clear":
            events = {}
            next_id = 0
        elif command == "insert":
            event_id = response["event_id"]
            assert event_id == f"evt_{next_id}"
            stored = copy.deepcopy(request["event"])
            stored["id"] = event_id
            events[event_id] = stored
            next_id += 1
        elif command == "batch_insert":
            valid = [item for item in request.get("events", []) if item.get("title")]
            assert response.get("inserted") == len(valid)
            for raw in valid:
                event_id = f"evt_{next_id}"
                stored = copy.deepcopy(raw)
                stored["id"] = event_id
                events[event_id] = stored
                next_id += 1
        elif command == "delete":
            event_id = request["event_id"]
            assert event_id in events
            assert response.get("deleted") == event_id
            del events[event_id]
        elif command == "list":
            returned = {
                item["id"]: item for item in response.get("events", [])
            }
            assert returned == events
    assert load_json("/tmp/calendar_state.json")["events"] == events


def test_emergencies_are_inserted_after_real_deletions():
    _, _, emergencies = inputs()
    entries = history()
    for emergency in sorted(
        emergencies, key=lambda item: (minute(item["arrival_time"]), item["_index"])
    ):
        insert_index = next(
            index for index, entry in enumerate(entries)
            if entry["response"].get("status") == "ok"
            and entry["request"].get("cmd") == "insert"
            and entry["request"].get("event", {}).get("task_id") == emergency["id"]
        )
        event = entries[insert_index]["request"]["event"]
        assert event["start"] == emergency["arrival_time"]
        assert any(
            entry["response"].get("status") == "ok"
            and entry["request"].get("cmd") == "delete"
            for entry in entries[:insert_index]
        )


def test_batch_variant_uses_batch_for_the_initial_plan():
    simulator = (APP / "api_simulator.py").read_text(encoding="utf-8")
    if 'action == "batch_insert"' not in simulator:
        return
    entries = history()
    batches = successful(entries, "batch_insert")
    assert len(batches) == 1
    first_insert = min(
        index for index, entry in enumerate(entries)
        if entry["response"].get("status") == "ok"
        and entry["request"].get("cmd") in {"insert", "batch_insert"}
    )
    assert entries[first_insert]["request"]["cmd"] == "batch_insert"

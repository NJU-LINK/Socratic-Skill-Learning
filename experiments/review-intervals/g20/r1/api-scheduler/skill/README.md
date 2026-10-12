# API Scheduler Skill Package

This skill package solves the **api-scheduler family** of tasks.

## Package Contents

- **SKILL.md**: Complete skill documentation covering the family definition, core algorithm, variation axes, and implementation checklist
- **solve.py**: Reference implementation demonstrating the skill in action

## What This Skill Solves

Tasks in the api-scheduler family require:
1. Reading a set of tasks with priorities, durations, and dependencies
2. Building a priority-ordered schedule within a work window
3. Submitting the schedule to a stateful calendar API
4. Handling emergencies that invalidate parts of the schedule
5. Replanning and resubmitting as needed

## Family Variations

The skill handles all spec-declared variations:
- **Priority methods**: urgency, eisenhower, weighted
- **Task volumes**: 3-12 tasks with varying total durations
- **Interruption patterns**: no emergencies, single emergency, multiple emergencies
- **Scheduling constraints**: dependencies, deadlines, work windows, duplicate titles
- **API capabilities**: basic, transient-errors, batch insertion

## Usage

The reference implementation (`solve.py`) demonstrates the complete workflow:
1. Reads `/app/tasks.json` for the concrete instance
2. Inspects `/app/api_simulator.py` for capability detection
3. Builds and submits the schedule via the API
4. Handles emergencies with replanning
5. Writes `/app/output.json` and `/app/history.jsonl`

To apply this skill to a new api-scheduler task, follow the algorithm documented in SKILL.md and adapt the reference implementation as needed.

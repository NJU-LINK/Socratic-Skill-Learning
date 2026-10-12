import { randomUUID } from "node:crypto";
import { runProcess, type ProcessResult } from "./process.js";

export class ContainerDeadlineError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ContainerDeadlineError";
  }
}

interface DockerExecOptions {
  timeoutSeconds?: number;
  user?: string;
  workdir?: string;
  env?: string[];
}

// GNU timeout supervises a separate process group inside the container. Its
// uniquely named diagnostics distinguish an actual deadline from a command
// that deliberately exits 124 or 137. The inner shell records normal exits.
// KILL is deliberate: TERM can end the monitored parent while a child ignores
// it, which makes GNU timeout return before a later --kill-after can fire.
const deadlineScript = String.raw`
duration=$1
deadline_label=$2
completion_label=$3
shift 3
original_lc_all_set=
original_lc_messages_set=
if [[ -v LC_ALL ]]; then original_lc_all_set=x; fi
if [[ -v LC_MESSAGES ]]; then original_lc_messages_set=x; fi
original_lc_all=$LC_ALL
original_lc_messages=$LC_MESSAGES
unset LC_ALL
export LC_MESSAGES=C
exec -a "$deadline_label" timeout --verbose --signal=KILL "$duration" bash -c '
  if [ "$1" = x ]; then export LC_ALL="$2"; else unset LC_ALL; fi
  if [ "$3" = x ]; then export LC_MESSAGES="$4"; else unset LC_MESSAGES; fi
  completion_label=$5
  shift 5
  "$@"
  status=$?
  printf "\n%s:%s\n" "$completion_label" "$status" >&2
  exit "$status"
' -- "$original_lc_all_set" "$original_lc_all" "$original_lc_messages_set" "$original_lc_messages" "$completion_label" "$@"
`;

/** Run a task command with a deadline enforced where the command executes. */
export async function runDockerExec(
  container: string,
  command: string[],
  options: DockerExecOptions = {},
): Promise<ProcessResult> {
  const execArgs = [
    "exec",
    ...(options.user ? ["-u", options.user] : []),
    ...(options.env ?? []).flatMap((value) => ["-e", value]),
    "-w", options.workdir ?? "/app",
    container,
  ];
  const originalCommand = ["docker", ...execArgs, ...command].join(" ");
  const seconds = options.timeoutSeconds;
  if (seconds === undefined || seconds === 0) {
    return await runProcess("docker", [...execArgs, ...command]);
  }
  if (!Number.isFinite(seconds) || seconds < 0) {
    throw new RangeError("Container command timeout must be a finite, non-negative duration");
  }

  const nonce = randomUUID();
  const deadlineLabel = `ssl-deadline-${nonce}`;
  const completionLabel = `SSL_COMMAND_COMPLETE_${nonce}`;
  const result = await runProcess("docker", [
    ...execArgs, "bash", "-c", deadlineScript, "--",
    `${seconds}s`, deadlineLabel, completionLabel, ...command,
  ], {
    // Docker exec startup is outside the in-container command's time budget.
    // Leave room for startup and timeout's process-group cleanup before treating a
    // stalled Docker connection as an infrastructure failure.
    timeoutMs: Math.ceil(seconds * 1000) + 15_000,
  });
  const completed = new RegExp(`\\n${completionLabel}:(\\d+)\\r?\\n`, "g");
  const completion = [...result.stderr.matchAll(completed)];
  const diagnostic = new RegExp(`^${deadlineLabel}: sending signal KILL to command 'bash'\\r?\\n?`, "gm");
  const deadlineExpired = diagnostic.test(result.stderr);
  const cleanResult: ProcessResult = {
    ...result,
    command: originalCommand,
    stderr: result.stderr.replace(completed, "").replace(diagnostic, ""),
    timedOut: deadlineExpired,
  };
  if (!result.timedOut && (deadlineExpired || completion.some((match) => Number(match[1]) === result.exitCode))) {
    return cleanResult;
  }

  // A lost exec connection or unavailable deadline supervisor cannot prove
  // the task stopped. Stop the whole container before allowing a caller to
  // report an infrastructure error; continuing would risk stray side effects.
  const stopped = await runProcess("docker", ["kill", container], { timeoutMs: 15_000 });
  const cleanup = stopped.exitCode === 0 && !stopped.timedOut
    ? "The task container was stopped."
    : `Container cleanup also failed: ${stopped.stderr.trim() || stopped.stdout.trim() || stopped.exitCode}`;
  throw new ContainerDeadlineError(
    `${result.timedOut ? "Docker exec exceeded its outer deadline" : "Container deadline supervisor did not complete"}. `
    + `${cleanup}\n${cleanResult.stderr.trim() || cleanResult.stdout.trim()}`,
  );
}

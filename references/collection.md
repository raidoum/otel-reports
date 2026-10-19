# Collect logs with the official CLI

## Prerequisites and locations

Use the official `otelcol-contrib` executable with the OTLP/HTTP receiver, file exporter, and health_check extension. Analysis uses Python's standard library. Do not depend on custom `otel-collector`, `codex-otel`, or project-specific management wrappers.

Find `otelcol-contrib` and `codex` on PATH and check their executable paths and versions. If the Collector is not on PATH, use an executable explicitly provided by the user or identified in the permitted target's installation information. If installation is needed, follow the [official installation instructions](https://opentelemetry.io/docs/collector/install/) for the OS, architecture, and available permissions. Do not hard-code a host's absolute path or fall back to another project or a custom wrapper.

`<skill>` is the directory containing the loaded `SKILL.md`. Reference the bundled configuration from that location. Start collection before launching the work Codex. Loading a skill cannot change an already-running Codex's OpenTelemetry settings or recover events emitted before collection began.

## Start collection

1. Identify the target project and output location. Default to `.telemetry/captures/` under the target's root. Do not reuse a capture without inspecting its state or append to an existing capture directory.
2. Bind the receiver and health check to loopback. Defaults are `127.0.0.1:4318` and `127.0.0.1:13133`. If occupied, leave the existing process running, choose other ports, and use the matching endpoint in Codex's export settings.
3. Create an unused directory for each capture, copy the configuration, and validate and launch the official CLI. The example below uses a POSIX shell; set its variables in the shell managing this capture. Replace `CODEX_OTEL_SKILL_DIR` with the loaded skill's actual location. Use `CODEX_OTEL_COLLECTOR` to specify the official executable explicitly.

```sh
set -eu
CODEX_OTEL_SKILL_DIR='<skill>'
CODEX_OTEL_COLLECTOR="${CODEX_OTEL_COLLECTOR:-$(command -v otelcol-contrib)}"
test -n "$CODEX_OTEL_COLLECTOR"
test -x "$CODEX_OTEL_COLLECTOR"
"$CODEX_OTEL_COLLECTOR" --version

CODEX_OTEL_CAPTURE_ROOT="${CODEX_OTEL_CAPTURE_ROOT:-$PWD/.telemetry/captures}"
mkdir -p "$CODEX_OTEL_CAPTURE_ROOT"
CODEX_OTEL_CAPTURE_ROOT="$(cd "$CODEX_OTEL_CAPTURE_ROOT" && pwd)"
CODEX_OTEL_CAPTURE_DIR="$(mktemp -d "$CODEX_OTEL_CAPTURE_ROOT/capture-XXXXXXXX")"
export CODEX_OTEL_CAPTURE_DIR
export CODEX_OTEL_HTTP_ENDPOINT="${CODEX_OTEL_HTTP_ENDPOINT:-127.0.0.1:4318}"
export CODEX_OTEL_HEALTH_ENDPOINT="${CODEX_OTEL_HEALTH_ENDPOINT:-127.0.0.1:13133}"
cp "$CODEX_OTEL_SKILL_DIR/assets/collector.yaml" "$CODEX_OTEL_CAPTURE_DIR/collector.yaml"
"$CODEX_OTEL_COLLECTOR" validate --config "$CODEX_OTEL_CAPTURE_DIR/collector.yaml"
# Launch only after validation succeeds.
nohup "$CODEX_OTEL_COLLECTOR" --config "$CODEX_OTEL_CAPTURE_DIR/collector.yaml" \
  > "$CODEX_OTEL_CAPTURE_DIR/collector.log" 2>&1 < /dev/null &
CODEX_OTEL_COLLECTOR_PID=$!
printf '%s\n' "$CODEX_OTEL_COLLECTOR_PID" > "$CODEX_OTEL_CAPTURE_DIR/collector.pid"
```

4. Check that the PID has not exited immediately and that the configured health URL returns HTTP 200. Inspect `collector.log` for errors such as port conflicts; do not report successful startup when it failed. Preserve failed capture directories and use a new one for each retry.
5. Save `capture.json` at startup. Record the actual capture ID, target directory, output directory, configuration snapshot, Collector version, resolved executable path, PID, process-start identifier, both endpoints, UTC start time, and state. On Linux, use `/proc/<pid>/exe` and the starttime field in `/proc/<pid>/stat`. On other OSes, use equivalent executable and process-start information; PID alone is not identity. Distinguish preparing, running, stopped, and failed states. `collector.pid` is a convenience file, not sufficient evidence for stopping a process.

A successful health check establishes receiver readiness. After launching Codex, verify actual `codex.conversation_starts` events and the intended conversation ID in `logs.jsonl`, then record the conversation in `capture.json`. Delivery of manually injected synthetic data does not verify that Codex itself is exporting.

## Launch Codex with standard commands

Use the standard `-c` option to enable OpenTelemetry for that invocation without rewriting configuration files. Enable both logs and traces. Leave prompt text logging disabled unless the user requests `log_user_prompt=true`. Tool arguments and results can still contain content, so redacted prompts do not make the entire capture anonymous.

The examples below use the endpoints from the previous section. Run from the target project and preserve the user's model, permission, and other options. If the receiver endpoint changes, change Codex's export endpoint to match.

```sh
CODEX_OTEL_OVERRIDE="otel={environment=\"local\",log_user_prompt=false,exporter={otlp-http={endpoint=\"http://${CODEX_OTEL_HTTP_ENDPOINT}/v1/logs\",protocol=\"json\"}},trace_exporter={otlp-http={endpoint=\"http://${CODEX_OTEL_HTTP_ENDPOINT}/v1/traces\",protocol=\"json\"}},metrics_exporter=\"none\"}"

# Interactive invocation.
codex --no-daemon -c "$CODEX_OTEL_OVERRIDE"

# Noninteractive alternative; do not run this after the interactive example.
codex --no-daemon exec -c "$CODEX_OTEL_OVERRIDE" 'Run the development loop according to the target task instructions'
```

Add `--yolo` to the chosen invocation only when the user requested it; the skill does not independently broaden permissions. Check the installed CLI's `codex --help` and `codex exec --help`. In the verified CLI, `--no-daemon` prevents shared-daemon configuration mix-ups, and noninteractive overrides belong after `exec`. For other versions, follow their help and verify effective settings through actual events.

If the running work Codex already exports to the selected endpoint, its subsequent events can be collected. Otherwise launch a new work Codex with the required settings. Do not leave a child interactive TUI running unattended inside the current conversation. Show the user the required command or use standard `codex exec` for unattended work.

## Inspect and stop collection

Use the capture identified by `capture.json`. Do not choose among several candidates merely by taking the most recently found PID. Distinguish verified process identity, health, output location and event counts, and arrival of the intended conversation's events.

Stop in this order:

1. Record the loop's end time in `capture.json` and check arrival of final work events such as the last relevant tool_result. The same Codex can stop this capture's Collector after the loop. If final arrival cannot be confirmed, report the missing evidence as a measurement limitation. Do not stop a shared Collector still used by another session.
2. Compare the saved PID, executable path, and process-start identifier with the live process. Do not signal a mismatched PID. If records are incomplete, identify the owned process using startup information within the permitted target. If the matching process is already absent, record that fact and mark the capture stopped.
3. Send `kill -TERM <verified-pid>` to the identified Collector and wait for exit. Use `wait <pid>` only for a child of the same parent shell. For a process started elsewhere, inspect its exit instead. Ctrl+C is also a normal shutdown for a foreground Collector. Do not kill processes by name or automatically escalate to SIGKILL. Preserve the error state and logs if shutdown fails.
4. Update `capture.json` with the exit state, UTC stop time, log locations, and whether Codex exit and export completion were confirmed. Distinguish Collector shutdown from complete delivery by Codex. Preserve shutdown logs and raw telemetry. A file remaining unchanged for a while does not establish export completion.

A capture started by an older helper can still be stopped by signaling the verified official process directly. Use startup records from the specified target and leave unrelated management files unchanged.

## Hand off a completed loop to analysis

When following AGENTS.md rules, finish the loop, record the target period's end time, verify arrival of final work events, stop this capture's Collector, and generate HTML. Pass the recorded loop end time to `extract --end` to exclude the analysis work.

Pass `logs.jsonl` and, when available, `traces.jsonl` from the location recorded in `capture.json` to the `inspect` and `extract` commands in SKILL.md. Match the intended conversation and period against actual events. Preserve raw logs and use a separate unused analysis directory. Report early termination, undelivered events, and incomplete trailing records as limits of the captured evidence.

## Official references

- [Collector configuration and validate](https://opentelemetry.io/docs/collector/configuration/#location): the standard CLI accepts a configuration file.
- [Collector SIGINT/SIGTERM handling](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.163.0/otelcol/collector.go): shutdown signals trigger pipeline shutdown.
- [Codex OpenTelemetry](https://learn.chatgpt.com/docs/config-file/config-advanced#observability-and-telemetry): standard export support and shutdown flushing.

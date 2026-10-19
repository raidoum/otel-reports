# otel-report

A Codex skill for starting and stopping standard OpenTelemetry collection and turning captured logs into an HTML work report. Reports cover major stages, activity timelines, detailed breakdowns, findings, and suggested changes to task instructions. Zoom into a stage and follow an activity's duration and modified files through to its commands and captured output.

## Repository scope

The repository root is the skill directory. Keep `SKILL.md`, `agents/`, `assets/`, `references/`, and `scripts/` together. Store captured telemetry, generated HTML, and analysis data in the project being analyzed.

## Installation in another environment

Install the skill from the target project's root directory. If the destination already contains the skill, update that repository instead of overwriting it.

```sh
mkdir -p .agents/skills
git clone <remote-url> .agents/skills/otel-report
```

If the parent project also uses Git, either exclude `/.agents/skills/otel-report/` in the parent repository or register the skill as a Git submodule. Exclude it when managing the repositories independently; use a submodule when the parent should pin the skill to a specific commit.

Requirements:

- Python 3. The scripts have been tested with Python 3.12 and use only the standard library.
- For collection: a Codex CLI with OpenTelemetry support and the official `otelcol-contrib` executable.
- For HTML generation: the shared `html` skill, installed separately. It must provide `SKILL.md`, `design-system/component-samples.html`, `design-system/document.css`, and `design-system/math-copy.js`. Pass its directory with `--html-skill`. This repository does not bundle that shared skill.

Collector and output locations can be configured for each environment. See [references/collection.md](references/collection.md) for collection and [SKILL.md](SKILL.md) for analysis.

## Usage

Ask Codex to use `$otel-report` and specify the target project and operation. For example: "Start collecting logs for this project" or "Stop this capture and analyze the completed loop in an HTML report."

For automatic use before and after a development loop, add invocation rules to the project's `AGENTS.md`. Installing the skill alone does not change Codex's OpenTelemetry export settings. Follow the collection procedure to check the export settings and start the Collector.

## Example AGENTS.md rules

Add the following to the target project's `AGENTS.md`:

```markdown
## Loop telemetry

- Before starting a loop, use $otel-report to check the capture and Codex OpenTelemetry export settings. If either is missing, follow the skill's collection setup procedure.
- At the end of a loop, use $otel-report to record the target period's end time, verify that the final work events have arrived, and stop the current capture. Then generate an HTML report covering major stages, detailed breakdowns, findings, and suggested changes to task instructions, and report its location.
```

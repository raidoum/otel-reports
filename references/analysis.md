# Analysis guidelines

## Interpreting time

Partition elapsed time into nonoverlapping stages. Model intervals, tool intervals, and background jobs can run concurrently. Do not add an outer exec wrapper and its inner tools as separate work. Merge overlaps within the same group and account for overlaps between different groups as concurrent work.

`codex.sampling` covers communication, generation, reception, and related processing. Do not equate TTFT with pure reasoning time or the remainder with pure text-generation time. A tool call's duration ends when its result or running-session ID is received; it is not the background command's entire execution time.

Match background jobs using the running-session ID from `exec_command` and the exit result from `write_stdin`. The endpoint is when completion was observed and can include polling or postprocessing delays. If there is no exit record, label the observed interval as unconfirmed rather than successful. Retain unmatched results and unknown span names as diagnostics.

Do not classify gaps as human waits without explicit question and answer timestamps. Time outside response intervals does not establish that unrecorded work occurred.

## Interpreting activities

Do not infer a command's purpose from its first line alone. A single call can include substantial code generation, apply_patch, Python edits to existing files, tests, and result retrieval. Inspect arguments and results for representative long intervals, failures and their surrounding work, and final fixes.

`files_written` is a limited extraction from heredocs, patches, and similar commands. Do not classify read-only references as modifications. Put only confirmed created or modified paths in the review's `files` fields. When one response writes several files, report the shared response duration rather than allocating it per file.

Do not embed project-specific stage names, condition counts, process names, or fixed dates into the reusable skill. Name activities according to each loop's actual task.

## Bottlenecks and suggestions

Distinguish long-running work from work that could be shortened. Separate required iterations, waits, and device operation from work hidden by concurrency and work that may have delayed final completion. Label durations calculated from configured settings as nominal rather than measured.

For each suggestion, include the observed fact and evidence, the relevant area of the task instructions, proposed wording ready to paste, the expected causal effect, added cost, and a next-run comparison metric. Treat effects as hypotheses unless a counterfactual comparison supports a quantified saving. A single trial does not establish recurrence rates or the effect of an instruction revision. Do not propose unnecessary confirmation steps or blanket approval gates.

Keep comparisons involving fresh implementation separate from comparisons that reuse an already-fixed implementation. Respect constraints such as prohibiting reuse of prior artifacts. Reducing run counts, measurement durations, or quality requirements does not demonstrate improvement under unchanged conditions.

When no suggestion is supported, set `improvement_status` to `"no_supported_proposals"` and explain why. Do not invent issues merely to produce a suggestion.

## Input formats and reduced evidence

Supported inputs are OTLP JSON or JSONL containing `resourceLogs/scopeLogs/logRecords` and `resourceSpans/scopeSpans/spans`. Equivalent snake_case field names are accepted. Convert binary protobuf and proprietary formats to supported JSON first. If a new Codex version uses different span names, report what events establish rather than reconstructing response intervals or reasoning time from duration fields.

When a conversation contains several turns, compare `inspect` output with prompt timestamps and task content. Do not assume the longest turn is the target. Exclude telemetry from the current analysis session. Do not infer missing content from truncated tool output.

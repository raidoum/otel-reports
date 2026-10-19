# review.json format

`extract` generates a template with this analysis's action IDs. The example below explains the format; it does not determine the actual stages or suggestions.

```json
{
  "analysis_id": "the analysis_id from analysis.json",
  "semantic_review_complete": true,
  "title": "A title describing the development work",
  "objective": "What the loop implemented and verified.",
  "conclusion": "The outcome and supported improvement candidates.",
  "action_labels": {
    "a0001": {"title": "Inspect the environment and inputs", "summary": "An explanation supported by the recorded operations.", "files": []}
  },
  "stages": [
    {
      "id": "stage-1", "title": "Review instructions and configure the run", "summary": "Describe the outcome of this stage.",
      "start_seconds": 0, "end_seconds": 30,
      "groups": [{"title": "Environment inspection", "action_ids": ["a0001"]}]
    }
  ],
  "timeline": {
    "lanes": [
      {"id": "lane-aggregate", "title": "Implement aggregation", "description": "CSV output", "kind": "implementation",
       "items": [{"id": "work-aggregate", "title": "Implement aggregation and CSV output", "summary": "Describe the changes confirmed in the associated operations.", "action_ids": ["a0001"]}]}
    ]
  },
  "improvement_status": "supported_proposals",
  "improvement_note": "Explain the strength and scope of the evidence.",
  "findings": [
    {
      "title": "Repeated rework caused by an environment issue", "observation": "The event established by the logs.",
      "action_ids": ["a0001"], "job_ids": [], "confidence": "High",
      "impact": "Distinguish observed duration from its effect on total completion time.",
      "proposal": {
        "instruction_area": "Preflight completion criteria (proposed insertion area)",
        "text": "Check the required conditions before execution.",
        "expected_effect": "This may reduce recurrence of the failure.",
        "tradeoff": "It adds preflight work.",
        "validation": "Compare same-cause failures and elapsed time to the first successful run."
      }
    }
  ]
}
```

- `analysis_id` prevents attaching a review to the wrong analysis.
- Set `semantic_review_complete` to true after Codex has reviewed activity names, stages, evidence, and suggestions. This flag does not require human approval.
- Stage times are seconds relative to the selected period's start. Begin at 0 and end at `analysis.scope.seconds`, with no gaps or overlaps. Adjacent stages must share the same boundary. Preserve fractional seconds.
- `stages` defines the major stages on the timeline's top row. Group work around explainable purposes and outcomes such as implementation, startup verification, measurement, and fixes. Do not create a stage for each command or response; use `groups` and `action_labels` for those details.
- An optional stage `short_title` supplies a compact chart label. Keep the full `title` in the selector and details. If a bar is too narrow, display its stage number instead of a truncated title.
- Assign every action to exactly one group. Put an action that crosses a boundary in the stage containing most of it; the renderer accounts for its overlap with the other stage separately. Concurrent activities do not justify overlapping stages.
- Provide an `action_labels` entry for every action with a meaningful name. Do not leave initial candidate labels or command prefixes as the final explanation.
- `files` is an array of confirmed created or modified paths, for example `["src/aggregate.py", "tests/test_aggregate.py"]`. Exclude read-only references. Supplement limited extraction by inspecting recorded edits such as Python updates to existing files.
- `timeline.lanes` defines semantic rows below the major stages. Choose categories appropriate to the target, such as guest environment implementation, measurement control, analysis and charts, fixes, build checks, measurements, and documentation. Do not create one row per command or fall back to generic individual-operation/background-job categories. Separate implementation from execution and place both on the same time axis to show concurrency.
- A lane's `kind` must be `implementation`, `fix`, `execution`, `documentation`, or `investigation`. Each item needs a unique `id`, a concrete `title` and `summary`, and either `action_ids` or `job_ids` as its time evidence. A measurement item might be `{"id":"work-measure","title":"Run the main measurement","summary":"Explain the observed completion result and accepted runs.","job_ids":["j0001"]}`. Do not use a job's launch action as the duration of the entire measurement.
- Activity times are calculated from the referenced OpenTelemetry records. When grouping multiple actions, retain separate bars for gaps rather than painting the entire envelope as work. Duration is the union of the selected intervals. Do not put the same action or job in multiple items. The chart need not include every action; monitoring and polling details can remain in stage breakdowns. Modified files come from `action_labels.files`; do not add read-only references.
- Show jobs without observed completion as dotted bars ending at the capture boundary. Do not describe that width as confirmed execution time. Older reviews without a timeline can fall back to a stage-only chart; new analyses must provide semantic timeline lanes.
- Each finding must reference at least one existing action or job. Do not assert causes absent from the captured output. A finding can omit `proposal` when the issue is supported but a remedy is not.
- Use `supported_proposals` when supported suggestions exist. Otherwise use `no_supported_proposals` with an explanation; retain only supported findings or leave them empty.
- Optional `instruction_context` can describe which original instructions were inspected and why section numbers remain unconfirmed. Quote only the permitted target's verified text and revision.

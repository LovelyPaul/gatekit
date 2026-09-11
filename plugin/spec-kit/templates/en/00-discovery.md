# {{project_name}} — discovery record

Written: {{date}} · Status: {{in progress | deepening complete}}

`/gatekit:discover` writes this file and `/gatekit:interview` reads it. The prose
is for people; the `gatekit-discovery` fence below is what the validator reads.
When they disagree, the fence wins.

## Pain list

Only events that actually happened in the last two weeks. "It's usually like
that" is not an event.

| # | Pain | Last happened | Frequency | Minutes per run | Waiting / blocked |
|---|---|---|---|---|---|
| 1 | {{one line}} | {{date}} | {{N per month}} | {{N min}} | {{none or detail}} |

## Chosen problem

{{One sentence with no solution in it. If it contains "tool", "system" or "feature", it is not a problem yet.}}

Candidates not chosen: {{numbered list or "none"}}

## Deadline

{{e.g. 4 weeks | none}} — with none, scope is cut by release order, never by time.

## Deepening gates

| Gate | Value |
|---|---|
| Real user | {{name · role, one person}} |
| Current way | {{numbered steps. This becomes the source for screen design}} |
| Frequency | {{N per month}} |
| Minutes per run | {{N min · N hours per month in total. Waiting is recorded separately}} |
| Cause | {{the last link of the why chain}} |
| Failed attempts | {{separate "failed" from "works but costly"}} |

```gatekit-discovery
{
  "problem": "{{problem sentence with no solution in it}}",
  "deadline": "{{4 weeks | none}}",
  "user": "{{name · role}}",
  "current_way": ["{{step 1}}", "{{step 2}}", "{{step 3}}"],
  "frequency_per_month": 0,
  "minutes_per_run": 0,
  "wait": "{{none | N days per case · what is blocked meanwhile}}",
  "why_chain": ["{{symptom}}", "{{why 1}}", "{{why 2}}", "{{why 3}}", "{{cause}}"],
  "failed_attempts": [
    {"tried": "{{what was tried}}", "result": "failed", "why": "{{why it did not work}}"}
  ],
  "unpassed": []
}
```

`deadline` and `wait` are `none` when there is none. `failed_attempts` is the
string `"not-applicable"` when there was nothing to try. `unpassed` lists the
gates (fence key names) the user chose to skip. The validator marks each as
`warn`, and interview carries it into the PRD as an assumption, not a fact.

## Open items

- [unconfirmed] {{answered, but not confirmed by the real user · who can confirm}}
- [user's preferred solution] {{a solution the user kept returning to. Kept for reference only}}

Write "none" here when there is neither. Do not leave the heading empty.

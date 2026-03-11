## Live benchmark compatibility matrix

Use the live benchmark harness output to compare models by **furthest stage reached** and **primary failure code**, not only by pass/fail.

### Stage ladder

- `S0_PROVIDER_REQUEST`: benchmark invoked the configured model/provider route
- `S1_VISIBLE_RESPONSE`: at least one visible model response arrived
- `S2_ACTIONABLE_RESPONSE`: a response was accepted as valid tool XML or grounded text
- `S3_TOOL_EXECUTION`: at least one tool batch executed
- `S4_CONCRETE_TARGET`: the run narrowed to a specific file, command, or issue
- `S5_EDIT_ATTEMPT`: the model attempted a workspace change
- `S6_POST_EDIT_VALIDATION`: the run validated or rescanned after an edit
- `S7_GROUNDED_COMPLETION`: the final answer was grounded in tool evidence

### Primary failure codes

- `P1_PROVIDER_AUTH`: auth / invalid-key failure
- `P2_PROVIDER_RATE_LIMIT`: rate-limit, credit, or capacity failure
- `P3_PROVIDER_OTHER`: other provider/transport failure
- `R1_BLANK_VISIBLE_RESPONSE`: no visible assistant content after retries
- `R2_BLANK_FINAL_RESPONSE`: the run ended with the benchmark's no-visible-response placeholder
- `T1_RAW_TOOL_PROTOCOL_FINAL`: final answer still contained raw tool protocol
- `G1_NO_CONCRETE_TARGET`: tool loop never narrowed to a specific target
- `G2_STUCK_IN_GUIDED_STAGE`: run stalled in guided mode before a concrete edit cycle
- `E1_NO_EDIT_ATTEMPT`: tools ran, but no edit was attempted
- `E2_EDIT_ATTEMPT_NO_EFFECTIVE_CHANGE`: an edit batch ran, but no lasting workspace change was detected
- `V1_NO_VALIDATION_AFTER_EDIT`: an edit happened without validation/rescan
- `U1_AUTONOMY_NOT_UNLOCKED_AFTER_VALIDATED_CHANGE`: validated changed files existed, but unlock criteria were still not met
- `S2_NO_GROUNDED_FINAL_AFTER_VALIDATED_CHANGE`: the run reached validated file changes but never produced a grounded final answer
- `S3_GROUNDED_FINAL_WITHOUT_EDIT_CYCLE`: a grounded-looking final answer arrived without a real edit/validation cycle
- `S1_UNGROUNDED_FINAL_SUMMARY`: final answer was not grounded in latest tool evidence
- `S4_NO_GROUNDED_COMPLETION_AFTER_PROGRESS`: fallback bucket when no cleaner failure dominates

### Suggested matrix columns

| Model | Furthest stage | Failure code | Guided | Auto | Changed files | Note |
|---|---|---|---:|---|---|---|
| `openrouter/x-ai/grok-code-fast-1` | `S7_GROUNDED_COMPLETION` | `PASS` | `3` | `yes` | `app/main_gui.py` | grounded edit + validation |

### Interpretation

- Optimize for **later furthest stages** across the whole model set.
- Fix the **most common failure code** before adding model-specific patches.
- Treat provider failures separately from controller/model failures.
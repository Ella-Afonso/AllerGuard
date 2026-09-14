# Demo recording guide

Target a clear recording of about 4 minutes 30 seconds. This is a proposed script; a video has not yet been recorded or uploaded.

## Before recording

1. Publish the reviewed `pages-demo/` fixes and check the public link in a private browser window. Local fixes do not change an already deployed site.
2. Run the checks in the root README, plus `node --test tests/pages_demo.test.cjs` (Node.js required for the browser-state regression tests).
3. Start the local Python dashboard with `python -m scripts.serve_dashboard`. Keep the public Pages tab and local application clearly labelled.
4. Prepare the existing AWS proof logs or screenshots, the cycle infrastructure README, and the architecture diagram. Use recorded evidence; there is no need to re-enable the schedule to record the video.
5. Hide account details, terminal credentials and unrelated tabs. Use only the fictional café and public historical recalls.
6. Rehearse once. Confirm 5 assessments, 2 silent outcomes and 3 pending reviews. Refresh or start a fresh session before recording.

## Screen-by-screen script

| Time | Show | Suggested narration |
|---|---|---|
| 0:00–0:25 | AllerGuard title and fictional café | “Small food businesses need to spot relevant recalls without spending the day reading every alert. AllerGuard checks recalls against recorded stock and ingredients, then brings uncertain or relevant cases to the owner.” |
| 0:25–0:50 | Business view | “This is a fictional café with a prepared inventory. Menu upload is future work. The system works from what the business has actually recorded, including missing batch information.” |
| 0:50–1:30 | Run replay; show 5 / 2 / 3 | “Five historical alerts enter the workflow. Two have no recorded link and stay quiet. Three need review. Silence is visible in the audit trail, so it is something we can inspect.” |
| 1:30–2:10 | Doritos explanation; draft and owner choice | “We stock this product, but its batch is unknown. That uncertainty must reach the owner. The model cannot downgrade the deterministic safety floor. Approving, editing or declining records a choice; it does not execute stock or customer actions.” |
| 2:10–2:50 | Record remaining choices; Audit and Diary | “Every outcome has a record. The daily diary links the decisions. Opening and closing remain unconfirmed until the owner answers. The original filing and later confirmation are separate evidence.” |
| 2:50–3:15 | Export; rerun replay | “The export includes both recall and diary evidence. Repeating the replay preserves decisions and does not create another set of events.” |
| 3:15–3:55 | AWS proof logs and architecture | “This separate recorded AWS run was triggered by EventBridge, executed in Lambda, and wrote to DynamoDB. It processed five replay alerts; the next scheduled poll was empty with the same watermark. Model proposals were injected and notifications disabled for this proof.” |
| 3:55–4:30 | Public URL, repository and close | “The public website lets you explore the workflow for free in a browser simulation. The repository includes the real Python workflow, tests and AWS evidence. AllerGuard makes relevant uncertainty visible while leaving consequential decisions with the owner.” |

Prefer demonstrating the real Python dashboard for the central workflow, then show the public URL as an accessible companion. If you record the Pages workflow instead, say “browser simulation” before running it. Do not imply that its button invokes Bedrock or DynamoDB.

## Expected evidence

- Initial simulated-notification replay: **11 events**, **3 pending**.
- Three distinct owner choices: **14 events**, **0 pending**.
- Diary filing: **15 events**; explicit diary confirmation: **16 events**.
- Replay afterward: counts and decisions unchanged.
- Historical AWS proof with notifications disabled: **8 audit rows**, **3 queue rows**, **6 ledger rows**, **1 business row**. These are a different run and should not be compared with the 16-event browser diary session.

## Before submitting

- Check the public URL and public repository without logging in.
- Verify the recording is audible, readable, within the submission limit, and plays without requesting access.
- Include the video, public demo, repository and architecture links in the submission.
- Confirm the selected track and current rules in the submission form.
- Submit and retain the confirmation. A prepared description is not a submitted entry.

Live SES/SNS delivery, inbox receipt, live FSA scheduled polling, full AgentCore attachment and exactly-once external delivery remain outside the recorded proof. Do not describe them as completed.

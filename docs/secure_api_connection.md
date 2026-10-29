# Secure API evaluation through GitHub Actions

For this project the API key can stay in a GitHub repository Secret. GitHub's runner reads it only during the manual API step. The ChatGPT conversation, project files and assistant do not need the plaintext key. This route is independent of the OpenAI Developers connector that previously rejected key creation.

## One-time setup

1. Revoke any key previously exposed in chat at https://platform.openai.com/api-keys and create a replacement on the official Platform. Do not send the replacement to the conversation.
2. Review and merge the project pull request that contains `.github/workflows/notice-api.yml`. If the PR is Draft, first use **Ready for review**, then **Merge pull request** and confirm. Do not delete or overwrite `main` to do this.
3. Open https://github.com/nomoretry/semiconductor-logistics-decarbonization/settings/secrets/actions . Use **Secrets → New repository secret**.
4. Enter `OPENAI_API_KEY` in **Name**, paste the new key into **Secret**, then choose **Add secret**. Use a Secret, not a Variable or a committed file. This action saves the secret; it does not call the model.

Repository owners can perform these operations. If a required button is unavailable, report the page and button state without including a key screenshot or value.

## First connection test

Open the repository's **Actions** tab, choose **Notice API evaluation (manual)**, then **Run workflow**. Select branch **main** and profile **smoke20**, then click **Run workflow**.

This explicitly authorizes that one run to evaluate at most 20 development texts using the recorded candidate model and a USD 0.05 program reservation cap. It never silently switches models. Actual API billing is separate from ChatGPT usage. The reservation uses recorded model rates and conservative request/output bounds; it is not an OpenAI account-wide hard spending limit.

The workflow has no push, pull-request or schedule trigger. Uploading code and adding the Secret do not start API requests. A second manual run is a new batch and can incur new charges, so inspect a failed run before choosing to rerun it.

After completion, open the run's **Summary** and the **notice-api-smoke20-...** artifact. The summary distinguishes completed model responses, API/transport errors, unattempted requests, mock-test transport and unavailable results. No completed responses means no model-accuracy result, not zero model accuracy. A successful 20-item development test is not a held-out performance claim.

If the first run succeeds, the separate **test400** profile evaluates the 400 frozen synthetic test texts once, with a USD 0.50 program reservation cap. Account credits, model availability and endpoint permissions are checked by the actual request. No guarantee of availability is made before this test. The candidate model ID currently lacks a published dated snapshot, so the manifest records that backend-version limitation.

## Sharing the outcome

Send the workflow-run URL back to the conversation. The assistant can inspect job status/logs and download the resulting artifact through the GitHub connection without receiving your key. A repository Secret is not installed into the assistant's separate filesystem and does not repair the OpenAI Developers connector itself.

The workflow uses read-only repository permissions, pinned official Actions, no persisted checkout credentials, and step-scoped injection of the key. Artifacts are limited to the evaluation directory, never the repository root or `.env` files. Logs must not be used to print credentials. Only trusted repository maintainers should be allowed to change code that can receive the Secret.

## Nullable response error correction

The first manual run, https://github.com/nomoretry/semiconductor-logistics-decarbonization/actions/runs/40958506319 , stopped after one request. Its artifact records `api_error` with no HTTP status or specific error code. The original runner incorrectly treated the presence of `error` as a failure, even when its value was `null`. Normal successful Responses objects include `error: null`; the corrected runner rejects only non-null errors and still validates response status, model identity and output schema.

This defect reproduces the recorded failure shape. The original response was discarded, so that first run cannot prove a completed inference or provide recoverable accuracy/usage. Its zero reported cost is not evidence that the provider charged nothing. The frozen notice data, prompt, model, prices and rules remain unchanged.

After merging this correction, start a **new Run workflow** on **main** with **smoke20**. Do not use **Re-run jobs** on the old run: the workflow checks out the triggering commit, which still contains the defect. The existing repository Secret can be reused; this parsing defect does not itself require a new key. A new run sends new requests and remains subject to the USD 0.05 program reservation cap.

## Official references

- OpenAI API authentication: https://developers.openai.com/api/reference/overview
- OpenAI nullable response-error example: https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat
- GitHub repository Secrets: https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets
- Manual workflows and the default-branch requirement: https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow

The workflow file must exist in the default branch before GitHub exposes its manual-dispatch entry. It is not ready to run merely because a feature-branch file or a repository Secret exists.

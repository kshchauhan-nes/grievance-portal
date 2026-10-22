# AI Feature Proposal — General Grievance Portal

**Status: proposal only. No AI calls, model dependencies, or AI-generated decisions are implemented in the current application.** This proposal is for review and approval before implementation.

## Objectives

Add narrowly scoped assistance that reduces repetitive work while preserving human authority over case decisions. AI must not determine whether a complaint is true, disclose a complainant's identity, change case status, approve verification, or make disciplinary/medical/legal decisions.

## Recommended implementation order

### Phase 0 — Prepare and evaluate (first)
- Define the exact data each proposed feature may access.
- Create a small synthetic test set with expected outputs; do not use real complaint records for initial experiments.
- Add an AI provider interface and a deterministic mock provider so tests do not require paid API calls or network access.
- Add timeouts, bounded retries, input/output size limits, logging without sensitive prompt content, and a kill switch.
- Record model/provider, prompt version, latency, error rate, and usage/cost metadata without recording unnecessary personal information.

### Phase 1 — Case summarization
- Produce a short, factual summary from the case description and authorized messages.
- Distinguish reported allegations from verified facts.
- Never include identity-vault fields unless explicitly required and separately authorized; default to excluding them.
- Show the source case text to authorized staff and require human review before a summary is saved or shared.

### Phase 2 — Category suggestions
- Suggest one or more existing categories based on the complaint text.
- Return a constrained schema: suggested category, brief rationale, and confidence/uncertainty indicator.
- Keep the user's original category and allow staff to reject the suggestion.
- Do not automatically alter priority, status, or escalation outcomes.

### Phase 3 — Draft replies
- Draft a neutral acknowledgement or request for clarification using approved templates and case context.
- Never send messages automatically in the first version. A staff member must edit and approve each draft.
- Do not promise a resolution date or make claims not supported by the case record or approved policy.

### Phase 4 — Duplicate-case assistance (only after evaluation)
- Compare a new case against authorized case metadata or text and show possible matches to an authorized reviewer.
- Do not merge, suppress, or reject complaints automatically.
- Carefully control cross-organization access; do not expose other complainants' identities or complaint text through similarity results.

## Architecture

1. Flask route validates the request and current user's authorization.
2. A small service layer constructs a minimized prompt from explicitly allowed fields.
3. Provider adapter calls the selected model, with strict timeout and output-size limits.
4. Server validates the returned JSON against an allowlisted schema; malformed output is treated as a failed request.
5. UI labels the result as AI-generated and presents it for human review.
6. Audit metadata records that assistance was requested and whether a human accepted/edited it, without copying sensitive prompt text into logs.

Keep the provider replaceable. Start with a mock provider in tests; choose a real provider only after reviewing its current data-retention terms, age/account requirements, pricing, and whether submitted data may be used for training. Never commit API keys; read them from environment variables or a secret manager.

## Privacy, security, and reliability requirements

- Do not send names, emails, phone numbers, identity-vault values, or verification references by default.
- Obtain organizational approval before sending any real complaint data to an external provider.
- Treat complaint text as untrusted input, including any instructions embedded inside it. The model must not be allowed to override authorization or call arbitrary tools.
- Never give the model direct database access or unrestricted tools.
- Enforce authorization in Flask before retrieval; the model is not a security boundary.
- Do not allow model output to directly update case status, priority, verification state, identity disclosure, or recipients.
- Provide graceful fallback when no provider key is configured, the network fails, rate limits are hit, or the output is invalid.
- Add tests for prompt injection, malformed output, timeout, unauthorized access, cross-organization isolation, data minimization, and misleading summaries.

## Evaluation and acceptance criteria

Before enabling a feature, evaluate a representative synthetic test set and require:
- No unauthorized cross-user or cross-organization information in outputs.
- Structured outputs validate against the expected schema.
- Summaries preserve key facts and clearly attribute unverified claims.
- Category suggestions can be rejected without changing stored case data.
- Draft messages require explicit human approval before sending.
- API failures do not break ordinary portal workflows.
- Token/cost and latency budgets are documented and observable.

## Free-first development approach

- Develop and test against a deterministic mock provider first.
- Keep model API calls optional behind configuration.
- Compare providers only after checking current free-tier availability, rate limits, privacy terms, and usage costs.
- Do not promise unlimited free API use; free tiers can change and may be unavailable to some accounts.

## Approval gate

Do not implement real AI integration until the project owner approves the initial feature, allowed data fields, provider, budget, retention policy, and evaluation criteria. Recommended first feature: **case summarization using only case text explicitly visible to the authorized authority, with human review and no automatic case updates.**

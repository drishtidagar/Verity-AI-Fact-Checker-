# Product Requirements — Verity

## Problem
Content, brand and product teams review PDFs containing statistics, dates, financial and technical claims. Manual verification is slow and source trails are often fragmented.

## Users
Content editors, product marketers, brand/communications reviewers and agency strategists.

## Job to be done
Before approving a document, identify checkable claims, see what needs correction and inspect the evidence in one workflow.

## MVP
PDF upload; claim extraction with page references; live web search; evidence-grounded verdicts; source preservation on AI errors; audit history; JSON export.

## Product principles
Evidence before verdict; explicit uncertainty; traceability; human review; cost-aware processing.

## Success metrics
Claim extraction yield, evidence coverage, audit completion rate, median review time, correction acceptance rate and technical failure rate.

## Roadmap
0–3 months: labelled evaluation set, reviewer feedback, source allowlists, caching and pilot.
3–6 months: shared workspaces, review queues, approved-claim library, recurring checks and cloud-drive/CMS integrations.
6–12 months: SSO, multilingual review, private source allowlists, API/webhooks and managed storage.

## Monetization hypotheses
Free evaluation tier; Team subscription; Business integrations and governance; Enterprise SSO, API and private deployment. Pricing requires willingness-to-pay validation.

## Risks
Search snippets can be incomplete; model reasoning can misread units/timeframes; provider limits change; AI visibility or fact verdicts are not ground truth; local SQLite may not be durable on hosted ephemeral storage.

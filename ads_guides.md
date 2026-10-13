# Google Ads API v25 - průvodce (výtah z developers.google.com/google-ads/api/docs, stav 2026-10-12)

# Google Ads API v25 - Limits, mutates, reporting (GAQL), account management

Compiled 2026-10-12 from the official guides (pages "Last updated" 2026-09-30 to 2026-10-07). v26 has been announced (Oct 2026); everything here is stated for v25 unless noted. Field lists are intentionally omitted - use the proto/field reference for those. Where the guides are silent, this file says so.

---

## 1. Access levels, quotas and limits

### Developer token sunset (important, new in Sept 2026)
- Developer tokens were **sunset on 2026-09-09**. API access level is now attached to the **Google Cloud project** that owns the OAuth client (user-auth flow) or the service account (service-account flow).
- Sending `developer-token` header is still accepted but "optional and ignored by the API servers". A future major version will start rejecting it. Updated client libraries and the official Google Ads MCP server can call without a developer token.
- Old tokens' access levels were transferred to Cloud projects used with them in the 90 days before the sunset. Token never used before the sunset -> unusable; calls to production fail with `AuthorizationError.CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION`.
- Re-associating a token with a new Cloud project is no longer supported; a new project must apply for access itself.
- A Google Ads manager account is **no longer required** to use the API; it is needed only to link and manage multiple accounts.
- Access level management lives at Cloud Console > "Google Ads API Overview" page (not the API Center in the MCC, which is deprecated). IAM roles that can manage it: Owner, Editor, Quota Administrator, Service Usage Admin.
- Inactivity: Google may revoke access unused for 90 consecutive days; the project falls back to Test access.
- Known issues (Oct 2026): Basic/Explorer rejected for Cloud projects on Free Trial or with suspended billing; some projects upgraded after 2026-09-09 still get `AUTHORIZATION_ERROR` on production (workaround: new project).

### Access levels (per Cloud project)
| Level | Can access | Daily operations | How to get |
|---|---|---|---|
| Test | test accounts only | 15,000 / day | automatic when the API is enabled in the Cloud project |
| Explorer | test + production | **2,880 / day on production**, 15,000 on test | Cloud Console > Google Ads API Overview > "Upgrade access level" > Apply (may be auto-approved) |
| Basic | test + production | 15,000 / day (both) | same page, from Explorer; requires **brand verification** of the Cloud project; automated review "within minutes" |
| Standard | test + production | unlimited | same page, from Basic; manual compliance audit, ~10 business days; tool must meet Required Minimum Functionality (RMF); may need demo login |
- "Per day" = sliding 24-hour window. Exceeding -> `QuotaError.RESOURCE_EXHAUSTED`.
- Test-level project calling a production account: v25+ `AuthorizationError.CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION`; v24 and older `ACTION_NOT_PERMITTED`.
- **Explorer restrictions** (need Basic/Standard): account creation (`CustomerService.CreateCustomerClient`), user management (`CustomerUserAccessInvitationService`, `CustomerUserAccessService`), planning (`KeywordPlan*Service`, `KeywordPlanIdeaService`, `AudienceInsightsService`, `ReachPlanService`), billing (`PaymentsAccountService`, `BillingSetupService`, `AccountBudgetProposalService`, `InvoiceService`).
- Permissible use (Standard only): Ad creation/management (all services) | Reporting (only `Search`/`SearchStream`/read-only) | Keyword research & recommendations (`RecommendationService`, `KeywordPlanIdeaService`, `KeywordPlanService`). Change via the "tool change" form.
- Multiple Cloud projects may hold different access levels.

### What counts as an operation (daily quota)
- One `Search` or `SearchStream` query = **1 operation**, regardless of rows/pages/stream batches.
- Paging with a valid `next_page_token` does **not** consume quota. An expired/invalid page token raises an error and **does** count.
- Mutate: **each operation inside the request = 1** (e.g., 2 ad group ads in one `MutateAdGroupAds` = 2).
- Any other request (e.g. `ListAccessibleCustomers`, `ListBatchJobResults`, `UploadClickConversions`, `UploadUserData`, `CreateOfflineUserDataJob`) = 1 per request.
- Requests rejected with a `GoogleAdsFailure` (validation errors etc.) **still count**. Network-level failures that never reach the service do not.
- Batch jobs: each operation still counts toward the daily limit.
- Guides do not state whether `validate_only` requests count against the daily quota (budget for them as if they do).

### Rate limits (short-term)
- QPS is limited per **customer ID** and per **Cloud project** independently, via a token bucket; exact limit varies with server load. Violation -> `QuotaError.RESOURCE_TEMPORARILY_EXHAUSTED`.
- Also exist: requests-per-minute and **operations-per-minute** limits (large batches against one account can hit the latter).
- Each paged `Search` request is a separate RPC for short-term rate limits (one logical query still = 1 daily op).
- Query resource throttling: `QuotaError.EXCESSIVE_SHORT_TERM_QUERY_RESOURCE_CONSUMPTION` -> wait **5 min**; `EXCESSIVE_LONG_TERM_QUERY_RESOURCE_CONSUMPTION` -> wait **30 min**. Track cost via `query_resource_consumption` in `SearchGoogleAdsResponse` / `SearchGoogleAdsStreamResponse`. Published benchmarks (resource units): 5-min window p50 6,000 / p70 30,000 / p95 1,800,000; 24-h window p50 16,000 / p70 90,000 / p95 8,400,000.
- Recommended: cap concurrent workers, client-side token-bucket limiter, queue with pause-on-error, batch operations.

### Request size limits
- Mutate: max **10,000 operations per request** (`RequestError.TOO_MANY_MUTATE_OPERATIONS`); **20,000** when all ops are `AdGroupCriterionOperation` (`MutateAdGroupCriteria`); max **100 action operations** in `GoogleAdsService.Mutate` (`RequestError.TOO_MANY_ACTION_OPERATIONS`).
- Billing / account budget services: **1 operation per mutate**; mutates only on accounts with **monthly invoicing** (`MutateError.MUTATE_NOT_ALLOWED`); wait **>= 12 h** between `AccountBudget`/`AccountBudgetProposal` changes on the same account (earlier may cause unrecoverable failures).
- Shopping `ProductPartition` tree-structure changes: max **2 Shopping ad groups per request** (`AdGroupCriterionError.OPERATIONS_FOR_TOO_MANY_SHOPPING_ADGROUPS`); bid-only changes exempt; batch jobs exempt.
- gRPC message max **64 MB** (client libs; gRPC default 4 MB). Oversize response -> gRPC `RESOURCE_EXHAUSTED` (code 8 / HTTP 429) without GoogleAdsError. Fix: fewer fields, SearchStream, or fewer ops per mutate.
- Repeated field too long -> `SizeLimitError.REQUEST_SIZE_LIMIT_EXCEEDED` (split requests).
- GAQL `IN` list max **20,000 items** (`QueryError.FILTER_HAS_TOO_MANY_VALUES`).
- `Search` page size is fixed at **10,000 rows**; setting `page_size` -> `RequestError.PAGE_SIZE_NOT_SUPPORTED`. No documented max for `LIMIT` or total rows.
- `DatabaseError.REQUEST_TOO_LARGE`: "data written is too large. Split the request".
- Rare `INTERNAL_ERROR` within limits = internal fan-out; reduce query size/complexity.

### Service-specific limits
- Keyword planning: `GenerateKeywordIdeas` / `GenerateKeywordHistoricalMetrics` / `GenerateKeywordForecastMetrics` = **1 QPS per CID**; `GenerateAdGroupThemes` 2 QPS per CID.
- AudienceInsights composition/suggested-targeting ~200/day per CID.
- Conversion uploads: 2,000 click/call conversions per request (`TOO_MANY_CONVERSIONS_IN_REQUEST`); 2,000 adjustments per request. Conversion value rules: 100,000 per account.
- User data: max 20 identifiers per `UserData`; 100,000 identifiers per `AddOfflineUserDataJobOperationsRequest`; `UploadUserData` max 10 ops / 100 identifiers.
- Invitations: one pending invitation per email per account (`EMAIL_ADDRESS_ALREADY_HAS_PENDING_INVITATION`); max 70 pending per account (`PENDING_INVITATIONS_LIMIT_EXCEEDED`).

### System (object) limits worth knowing
- Hierarchy: test accounts per MCC hierarchy 50; managers per account **5** (`TOO_MANY_MANAGERS`); max depth **6** levels (`MAX_DEPTH_EXCEEDED`); pending manager invites per hierarchy 20 (`TOO_MANY_INVITES`); account count per hierarchy varies (`TOO_MANY_ACCOUNTS`).
- Names: account 255 chars; campaign 256; ad group 256 (`AdGroupError.INVALID_ADGROUP_NAME`).
- RSA: headline 30, description 90, path1/path2 15 chars (`AdError.LINE_TOO_WIDE`). Ad final URL 2,084 bytes incl. protocol; criterion final URL 2,047 bytes.
- Keyword text 80 chars (`KEYWORD_TEXT_TOO_LONG`); placement URL 250 chars (protocol stripped); proximity radius max 800 km / 500 mi; excluded IP blocks 500 per campaign.
- Budgets: 11,000 shared and 20,000 unshared per account; no limit on campaigns sharing a budget. 1,000 bidding strategies attached to ad groups per campaign.
- Labels: 100,000 label applications per account (all entity types); 50 per entity; MCC: 200 account labels, label on max 1,000 accounts.
- Listing groups: 20,000 per ad group.
- Performance Max: 100 PMax campaigns per account (higher via Google rep); 100 asset groups per campaign; 1,000 listing group filters per asset group; listing group tree depth 7 (`TREE_TOO_DEEP`).
- String byte limits are computed on UTF-8.

Zdroj: https://developers.google.com/google-ads/api/docs/api-policy/developer-token , https://developers.google.com/google-ads/api/docs/api-policy/access-levels , https://developers.google.com/google-ads/api/docs/api-policy/rate-sheet , https://developers.google.com/google-ads/api/docs/best-practices/quotas , https://developers.google.com/google-ads/api/docs/best-practices/system-limits , https://developers.google.com/google-ads/api/docs/productionize/rate-limits , https://developers.google.com/google-ads/api/docs/productionize/manage-data-efficiently , https://developers.google.com/google-ads/api/docs/reporting/paging

---

## 2. Mutates: best practices and gotchas

### Three ways to mutate
- **Resource service** (e.g. `CampaignService.MutateCampaigns`): one resource type per call. Each operation = one of `create` (new object), `update` (object + `update_mask`), `remove` (resource_name string). `CustomerService.MutateCustomer` takes a singular `operation`.
- **`GoogleAdsService.Mutate`** (bulk): list of `MutateOperation` across resource types + action ops (`book_campaigns_operation`, `quote_campaigns_operation`). Needed whenever operations reference temp IDs of a **different** resource type. `quote_campaigns_operation` requires `validate_only=true` and `partial_failure=false`.
- **`BatchJobService`** (async): large/long workloads; always partial-failure semantics; no `validate_only`; no action ops.
- Cross-account mutation is generally not permitted (except a manager of the client that created the object).

### Atomic vs partial_failure
- Default: **atomic** - any failing op rolls back the whole request.
- `partial_failure=true`: valid ops commit; failed ops get an **empty entry in `results`** (same order as request). Errors in `partial_failure_error` (`google.rpc.Status`) whose `details` has exactly one `GoogleAdsFailure`; each `GoogleAdsError.location.field_path_elements[0].index` = 0-based operation index. In Python the field is always present - check `partial_failure_error.code != 0`.
- A method supports partial failure only if its request message has a `partial_failure` field (`OfflineUserDataJobService.AddOfflineUserDataJobOperations` uses `enable_partial_failure`). Known non-supporting ops: `CustomerOperation`, `CampaignConversionGoalOperation`, `ConversionGoalCampaignConfigOperation`, `CustomConversionGoalOperation`, `CustomerConversionGoalOperation` (-> `MutateError.OPERATION_DOES_NOT_SUPPORT_PARTIAL_FAILURE` in batch jobs).
- With partial failure, if a parent op defining a temp ID fails, dependent children fail with `NewResourceCreationError.TEMP_ID_RESOURCE_HAD_ERRORS`. Docs recommend **not** using partial failure for interdependent (temp-ID) operations.
- PMax: with `brand_guidelines_enabled` (default true) the `Campaign` + brand `CampaignAsset`s (business name, logo) are created together - treat as atomic. When an asset group first receives its required assets, send them **in one request without partial failure**; later single-asset add/remove may use partial failure.
- OfflineUserDataJob can finish `SUCCESS` even if all ops were invalid - always check `partial_failure_error` on each add-operations response.
- A successful response status does not mean every op succeeded when partial failure is on.

### validate_only
- `validate_only=true` checks the request (structure and policy) without committing. Supported on `GoogleAdsService.Search` and most mutates; **not** on `SearchStream`; not in `BatchJobService`.
- Resource mutate ops: returns only validation errors, no results. Action ops: returns the action result (e.g. quote) when valid.
- v25: Smart campaign PMax generation rejects `validate_only` (`SmartCampaignError.VALIDATE_ONLY_GENERATE_PMAX_NOT_SUPPORTED`).
- Good pattern for a UI-replacement assistant: run validate_only first, show errors/policy findings, then send the real request.

### Temporary resource IDs (negative IDs)
- Supported in `GoogleAdsService.Mutate` and `BatchJobService`. Set `resource_name` of the new object to e.g. `customers/CID/campaigns/-1`; reference it from later ops; API substitutes the real ID.
- Rules: define before use (order matters); scope = one request / one batch job (never across requests); each negative number unique **across all resource types** in the request (`NewResourceCreationError.DUPLICATE_TEMP_IDS`); `0` is not allowed.
- In a resource-service mutate you cannot give a temp ID to a parent of another type; self-referencing temp IDs within the same resource type are supported.
```json
{"mutateOperations":[
 {"campaignBudgetOperation":{"create":{"resourceName":"customers/CID/campaignBudgets/-1","amountMicros":"10000000"}}},
 {"campaignOperation":{"create":{"resourceName":"customers/CID/campaigns/-2","campaignBudget":"customers/CID/campaignBudgets/-1"}}},
 {"adGroupOperation":{"create":{"resourceName":"customers/CID/adGroups/-3","campaign":"customers/CID/campaigns/-2"}}},
 {"adGroupAdOperation":{"create":{"adGroup":"customers/CID/adGroups/-3"}}}]}
```
(other required fields omitted)

### Order and grouping of operations
- `GoogleAdsService.Mutate` batches **contiguous** ops of the same type into one backend call. Group by type in dependency order (budgets -> campaigns -> ad groups -> criteria/ads). Interleaving (`[campaign, adgroup, campaign, adgroup]`) multiplies backend calls and can time out large requests.
- Batch jobs: order by type, group by parent within type, keep related ops consecutive.
- Results always come back in request order.

### Update masks (FieldMask)
- `update` ops need `update_mask`; fields not in the mask are left unchanged ("sparse updates" - faster, fewer errors). Send only changed fields.
- Python: `client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, obj._pb))` derives the mask from fields set on the object.
- **Clearing a field**: leave the field unset (JSON `null`) **and explicitly include its path in `update_mask`** (e.g., removing an ad group criterion `cpc_bid_micros` override). A mask derived only from set fields will not clear anything.
- When mutating an object fetched by a query, send a mask - otherwise you risk `READ_ONLY_FIELD` / `IMMUTABLE_FIELD` errors or overwriting attributes.
- Immutable examples documented: `ConversionAction.type`, `ConversionAction.app_id`, location criteria (to change geo targets: remove + create in one `MutateCampaignCriteria` call), Customer `currency_code`/`time_zone` are set at creation (`CreateCustomerClient`).
- Ads: via `AdGroupAdService` only status (and ad_group_ad-level fields) can change - otherwise `AdError.CANNOT_USE_AD_SUBCLASS_FOR_OPERATOR`; ad content updates go through `AdService.MutateAds` (supported e.g. for RSA); otherwise create a new ad and remove the old one. Removed ads cannot be updated (`CANNOT_OPERATE_ON_REMOVED_ADGROUPAD`).

### response_content_type
- Default `RESOURCE_NAME_ONLY`. `MUTABLE_RESOURCE` returns resource_name + the resource with its mutable fields (plus key system fields, e.g. `ExperimentArm.in_design_campaigns`) for create/update. `remove` and unsupported types always return only resource_name. Saves a follow-up Search, larger payload.

### Concurrency and retries
- Concurrent mutations on the same campaign/account can raise `DatabaseError.CONCURRENT_MODIFICATION` ("Multiple requests were attempting to modify the same resource at once. Retry the request."). Avoid parallel writers on the same entities; retry with backoff.
- `DatabaseError.DATA_CONSTRAINT_VIOLATION`: usually becomes a more specific error if retried.
- Retryable: gRPC `UNAVAILABLE`, `DEADLINE_EXCEEDED`, `INTERNAL`, `UNKNOWN`, `ABORTED`; `InternalError.INTERNAL_ERROR` / `TRANSIENT_ERROR`. Use exponential backoff with jitter (examples: 1-2-4 s or 5-10-20 s). `DEADLINE_EXCEEDED`: wait ~30 s then retry; if persistent, split request. `RESOURCE_EXHAUSTED`: back off and lower rate.
- Do NOT retry until fixed: `INVALID_ARGUMENT`, `NOT_FOUND`, `PERMISSION_DENIED`, `FAILED_PRECONDITION`, `UNAUTHENTICATED`, `DATA_LOSS`, `UNIMPLEMENTED`.
- Newly created account: `AuthenticationError.CUSTOMER_NOT_FOUND` -> wait 5 min, then retry every 30 s.
- Log `request-id` (response header / `GoogleAdsFailure.request_id`; each stream response carries one).

### Other common mutate errors
- `DUPLICATE_CAMPAIGN_NAME` / `DUPLICATE_ADGROUP_NAME`: name already used by an enabled or paused entity.
- `AssetError.DUPLICATE_ASSET`: two creates with identical binary in one request - separate requests or temp ID.
- `DistinctError.DUPLICATE_ELEMENT`: duplicate values in a list.
- `MutateError.RESOURCE_NOT_FOUND`: wrong/removed resource name - use names from search results.
- `BiddingError.BID_TOO_MANY_FRACTIONAL_DIGITS`: micros not a multiple of the currency's minimum unit (e.g. USD 0.015 invalid). `CampaignBudgetError.NON_MULTIPLE_OF_MINIMUM_CURRENCY_UNIT` same for budgets.
- `CampaignError.CANNOT_SET_CAMPAIGN_KEYWORD_MATCH_TYPE`: with AI Max on, use ad-group `disable_search_term_matching` instead.
- `KEYWORD_HAS_INVALID_CHARS` / `INVALID_KEYWORD_TEXT`: e.g. `! @ % *`.
- `RangeError.TOO_LOW` often = ID left at 0.

### Batch jobs (BatchJobService)
- Use when: very many ops, want async + automatic retry of transient errors, or creating complex hierarchies; docs warn it does **not** guarantee higher throughput or faster completion.
- Flow: `MutateBatchJob` (create, status `PENDING`, optional `metadata.execution_limit_seconds`) -> `AddBatchJobOperations` (first call without `sequence_token`, then pass `next_sequence_token`) -> `RunBatchJob` (returns LRO, status `RUNNING`, no more adds) -> poll `GetOperation` until `done` (metadata: `estimated_completion_ratio`, `executed_operation_count`) -> `ListBatchJobResults` (results by `operation_index`; success = `mutate_operation_response`, failure = `status`).
- Cancel: before run - remove the PENDING job via `MutateBatchJob`; after run - `CancelOperation` on the LRO (completed ops are not rolled back).
- Limits: 1,000,000 ops per job (`RESOURCE_LIMIT` `BATCH_JOB_OPERATIONS_PER_JOB`); **100 active/pending jobs per account**; pending jobs older than 7 days auto-removed; 10,000 ops per `AddBatchJobOperations` (recommended <= 1,000); request max 41,937,920 bytes; single op max 10,484,504 bytes (`BatchJobError.REQUEST_TOO_LARGE`); result `page_size` default/max 1,000 (`INVALID_PAGE_SIZE`).
- Errors: `RESULTS_NOT_READY`, `EMPTY_OPERATIONS`, `INVALID_SEQUENCE_TOKEN`, `CANNOT_MODIFY_JOB_AFTER_JOB_STARTS_RUNNING`, `CANNOT_LIST_RESULTS`.
- Internal sub-batches of up to 1,000 ops. Atomic sub-batches: AssetGroup create + following AssetGroupAsset creates (`ASSET_GROUP_AND_ASSET_GROUP_ASSET_TRANSACTION_FAILURE`); PMax Campaign create (brand guidelines on) + CampaignAsset creates (`CAMPAIGN_AND_CAMPAIGN_ASSET_TRANSACTION_FAILURE`); consecutive AssetGroupListingGroupFilter ops on one asset group (max 10,000, `ASSET_GROUP_LISTING_GROUP_FILTER_TRANSACTION_FAILURE`); consecutive listing-group AdGroupCriterion ops on one ad group (max 20,000, `CriterionError.LISTING_GROUP_ERROR_IN_ANOTHER_OPERATION`). Put prerequisite Asset creates **before** the parent, never between parent and its links. When an atomic sub-batch fails, the culprit has the real error, the rest a transaction error.
- Do not mutate the same object twice in one job (unpredictable); avoid many concurrent RUNNING jobs touching the same objects (deadlock-like failures). Don't poll too often.
- Unsupported in batch jobs: `CustomerOperation`, conversion-goal ops listed above, `BookCampaignsOperation`/`QuoteCampaignsOperation` (-> `INTERNAL_ERROR`). Run those via `GoogleAdsService.Mutate` with `partial_failure=false`.

### Policy violation exemptions
- Mutate of an object with policy issues throws `GoogleAdsError` with `ErrorDetails`:
  - **Ads**: `error_code.policy_finding_error` (`PolicyFindingError`), details in `details.policy_finding_details.policy_topic_entries[]`.
  - **Keywords**: `error_code.policy_violation_error` (`PolicyViolationError`), details in `details.policy_violation_details` (has `key` = `PolicyViolationKey{policy_name, violating_text}` and an `is_exemptible` flag).
- **Ads workflow**: collect `topic` of every `PolicyTopicEntry` -> resend with `policy_validation_parameter.ignorable_policy_topics=[...]` on `AdGroupAdOperation` (create, `AdGroupAdService.MutateAdGroupAds`) or `AdOperation` (update, `AdService.MutateAds`). Same for all ad types.
- **Keywords workflow**: verify all violations are exemptible; collect keys -> resend create with `AdGroupCriterionOperation.exempt_policy_violation_keys=[...]`. Non-exemptible violations cannot be exempted - change the text.
- Exemption = a review request, not a guaranteed approval (ad/keyword then goes through review).
```json
{"operations":[{"create":{"adGroup":"customers/CID/adGroups/AGID","ad":{...}},
 "policyValidationParameter":{"ignorablePolicyTopics":["PUNCTUATION"]}}]}
```
(topic string is whatever the error returned; "PUNCTUATION" is illustrative)

### Warnings (non-blocking errors)
- Only `OfflineUserDataJobService.AddOfflineUserDataJobOperations` and `MutateCustomerSkAdNetworkConversionValueSchema` support `enable_warnings`; read `response.warning` (Status with GoogleAdsFailure).

Zdroj: https://developers.google.com/google-ads/api/docs/mutating/overview , https://developers.google.com/google-ads/api/docs/mutating/service-mutates , https://developers.google.com/google-ads/api/docs/mutating/bulk-mutate , https://developers.google.com/google-ads/api/docs/mutating/best-practices , https://developers.google.com/google-ads/api/docs/best-practices/overview , https://developers.google.com/google-ads/api/docs/best-practices/partial-failures , https://developers.google.com/google-ads/api/docs/best-practices/testing , https://developers.google.com/google-ads/api/docs/best-practices/error-types , https://developers.google.com/google-ads/api/docs/best-practices/common-errors , https://developers.google.com/google-ads/api/docs/best-practices/understand-api-errors , https://developers.google.com/google-ads/api/docs/best-practices/warnings , https://developers.google.com/google-ads/api/docs/batch-processing/overview , https://developers.google.com/google-ads/api/docs/batch-processing/flow , https://developers.google.com/google-ads/api/docs/batch-processing/best-practices , https://developers.google.com/google-ads/api/docs/policy-exemption/overview , https://developers.google.com/google-ads/api/docs/policy-exemption/ads , https://developers.google.com/google-ads/api/docs/policy-exemption/keywords , https://developers.google.com/google-ads/api/docs/campaigns/bidding/set-bids , https://raw.githubusercontent.com/googleapis/googleapis/master/google/ads/googleads/v25/errors/database_error.proto

---

## 3. Reporting and GAQL

### Grammar essentials
```
SELECT f1, f2 FROM resource [WHERE cond AND cond ...] [ORDER BY f [ASC|DESC], ...] [LIMIT n] [PARAMETERS k=v, ...]
```
- Operators: `= != > >= < <= IN, NOT IN, LIKE, NOT LIKE, CONTAINS ANY|ALL|NONE, IS NULL, IS NOT NULL, BETWEEN a AND b, DURING, REGEXP_MATCH, NOT REGEXP_MATCH`.
- **Only `AND`** - no `OR`; use `IN` or `REGEXP_MATCH` (RE2) instead. No joins beyond implicit attributed resources; exactly one resource in `FROM`.
- Strings in single or double quotes; escapes `\\ \' \" \n \r \t`. `LIKE` on string fields only (not arrays); escape literal `[ ] % _` by wrapping in brackets: `LIKE '[[]Earth[_]to[_]Mars[]]%'`.
- Case sensitivity: `= != IN NOT IN CONTAINS*` case-sensitive; `LIKE` case-insensitive; `REGEXP_MATCH` case-sensitive unless pattern starts with `(?i)`.
- Enum values can be written bare (`segments.device = MOBILE`) or quoted (`campaign.status = 'PAUSED'`).
- `PARAMETERS include_drafts=true` returns draft entities; `omit_unselected_resource_names=true` suppresses auto-returned resource_name fields.
- `resource_name` of the FROM resource is always returned (and of each attributed resource with a selected field). `resource_name` can be used in WHERE/ORDER BY.
- You can select only metrics, or only segments, from a resource; main resource fields need not be selected to filter on them.
- Cannot select: non-`selectable` fields, sub-fields of repeated fields, fields not available for the FROM resource, incompatible segment/metric combos. Use `GoogleAdsFieldService` (query has **no FROM**) to read `selectable`, `filterable`, `sortable`, `selectable_with`, `is_repeated`: `SELECT name, selectable_with WHERE name = "segments.hour"`.

### Metrics vs attributes vs segments
- Attributes = resource fields (`campaign.name`); metrics = `metrics.*` (aggregated); segments = `segments.*` split rows. Every report is implicitly segmented by the FROM resource. Selecting a field of a "segmenting resource" (e.g. `campaign.name` FROM `campaign_budget`) further segments by that resource.
- Each added segment can multiply rows; the API (unlike the UI) allows multiple segments at once.
- `segments.keyword.*` implicitly restricts to Search keyword rows - drops DSA, Shopping and PMax rows.
- Joint requirements: `segments.ad_sub_network_type` needs `segments.ad_network_type` in SELECT; v25: `segments.ad_sub_format_type` needs `segments.ad_format_type`.
- v24+: `segments.click_type` not selectable with `ad_group_asset`/`campaign_asset`/`customer_asset`; `segments.ad_sub_network_type` not with `campaign_budget`.
- Money in micros (`cost_micros` / 1,000,000). All dates are in the account time zone (`customer.time_zone`).

### Date ranges
- Custom: `segments.date BETWEEN '2026-01-01' AND '2026-01-31'` or `>= <=`; format `YYYY-MM-DD` (or `YYYYMMDD`).
- `DURING` only with literals: `TODAY, YESTERDAY, LAST_7_DAYS, LAST_14_DAYS, LAST_30_DAYS` (exclude today), `LAST_BUSINESS_WEEK, THIS_MONTH, LAST_MONTH, THIS_WEEK_SUN_TODAY, THIS_WEEK_MON_TODAY, LAST_WEEK_SUN_SAT, LAST_WEEK_MON_SUN`. No LAST_90_DAYS etc. - use BETWEEN.
- Core date segments: `segments.date, week, month, quarter, year`. They are the only segments filterable in WHERE without being selected. **If any core date segment is selected, WHERE must contain a finite date range on core date segments.** Invalid: `SELECT campaign.name, segments.date FROM campaign` (no range).
- `segments.week` = Monday date; `segments.month` = `YYYY-MM-01`; `segments.quarter` = first day of quarter; misaligned -> `QueryError.MISALIGNED_DATE_FOR_FILTER`. `segments.year = 2026` (integer).
- **Data retention (since 2026-06-01)**: daily/weekly/hourly granularity (`segments.date`, `segments.week`, `segments.hour`, sub-monthly ranges) only **37 months** back -> otherwise `DateRangeError.REQUESTED_DATE_GRANULARITY_NOT_SUPPORTED` (v24+). Monthly/quarterly/yearly or unsegmented: **11 years**, aligned to the next full calendar period. For older data use `segments.month` with a range from the 1st of a month to the end of a month.
- Not documented in guides: default date range when a metrics query has no date filter.

### Zero-metric rows
- Unsegmented queries can return rows with all-zero metrics (paused/ineligible entities). Exclude with e.g. `WHERE metrics.impressions > 0`.
- When any `segments.*` field is selected, rows where **all selected metrics are zero** are omitted (e.g., dates without traffic disappear). Filtering on a date in WHERE without selecting it does not count as segmenting.
- Criteria views (`keyword_view` etc.) exclude criteria with no impressions and **negative criteria** (no metrics ever).

### Search vs SearchStream, paging, LIMIT
- `SearchStream`: one request, persistent stream of batches; typically faster for multi-page results; process chunks as they arrive. No `validate_only`. Configure RPC timeouts and retry on stream interruption.
- `Search`: pages of exactly <= 10,000 rows; pass `next_page_token` as `page_token` with the **identical query**; token TTL ~2 h (`EXPIRED_PAGE_TOKEN`-type error -> restart query); last page has no token. Client libraries page automatically; REST must page manually.
- Both: 1 daily operation per logical query. No difference under 10,000 rows.
- `LIMIT n` caps rows (top-N with ORDER BY). Max LIMIT not documented. Docs suggest `LIMIT` or ID filters to split huge reports.
- ORDER BY: only on selected attributes/metrics/segments; not on MESSAGE-type or repeated fields. Default ASC.
- Filtering: not on unselected segments (except core date), not on message-type fields.

### UI vs API differences
- **UI hides removed entities; the API returns them** - add `WHERE campaign.status != 'REMOVED'` (or `IN ('ENABLED','PAUSED')`) to match UI.
- No scheduled/emailed reports, no CSV/TSV/XML output - the client formats data.
- UI view -> resource: Account `customer`; Campaign `campaign`; Ad group `ad_group`; Ads `ad_group_ad`; Search keywords `keyword_view`; Search terms `search_term_view`; Paid & organic `paid_organic_search_term_view` (needs Search Console linked at customer level); Landing pages `landing_page_view` / `expanded_landing_page_view`; Placements `managed_placement_view`; Where ads showed `group_placement_view` / details `detail_placement_view`; Age `age_range_view`; Gender `gender_view`; Locations `location_view`; Topics `topic_view`; Geographic `geographic_view`.

### change_event and change_status
- `change_event`: field-level history (old_resource/new_resource, `changed_fields`, `client_type`, `user_email` when visible in UI Change History, `resource_change_operation`).
  - WHERE on `change_event.change_date_time` **within the past 30 days** - required.
  - **`LIMIT` required, max 10,000.** To get more, re-query starting after the last returned timestamp.
  - Up to ~3 min latency. Not every UI Change History row appears; **Google Ads Editor changes not supported**; criterion-level changes not supported (use change_status).
- `change_status`: which resources changed (resource_status `ADDED`/`CHANGED`/`REMOVED`, only latest change per resource).
  - WHERE on `change_status.last_change_date_time` **within the past 90 days** - required; **`LIMIT` required, max 10,000** (narrow time windows to get more).
  - Tracks ad group, ad group ad, ad group bid modifier, ad group criterion, ad group feed, asset group, campaign, campaign budget, campaign criterion, campaign feed, feed, feed item, shared set, campaign shared set, asset, asset set, customer asset, campaign asset, campaign asset set, ad group asset. A child change may flag the parent. No field diffs - re-query by `resource_name`.
```sql
SELECT change_event.change_date_time, change_event.change_resource_type, change_event.change_resource_name,
  change_event.client_type, change_event.user_email, change_event.resource_change_operation,
  change_event.changed_fields, change_event.old_resource, change_event.new_resource
FROM change_event
WHERE change_event.change_date_time >= '2026-10-01' AND change_event.change_date_time <= '2026-10-12'
ORDER BY change_event.change_date_time DESC
LIMIT 1000
```

### Common reports
- **Search terms (Search/Shopping, ad group level)**: `search_term_view` (implicitly segmented by ad group - same term can repeat per ad group). RMF lists `search_term_view.search_term`, `segments.search_term_match_type`, clicks, cost, impressions.
```sql
SELECT search_term_view.search_term, segments.search_term_match_type, campaign.id, ad_group.id,
  metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions
FROM search_term_view WHERE segments.date DURING LAST_30_DAYS AND metrics.impressions > 0
```
- **Search terms incl. PMax**: `campaign_search_term_view` (campaign-level aggregation, PMax + Search). `search_term_view` "does not include data for Performance Max". Adding keyword-related segments (e.g. `segments.keyword.info.text`) filters out all PMax data.
- **Search term insights (categories)**: `customer_search_term_insight` and `campaign_search_term_insight` group terms into categories with volume/metrics; history from March 2023. Docs: query the customer-level one first, then refine; frequent `campaign_search_term_insight` use can return `RESOURCE_EXHAUSTED`. (Guides do not document the exact mandatory filters; check `selectable_with`/errors.)
- **PMax**: no ad groups/ads - `ad_group`/`ad_group_ad` return nothing. Use `campaign` (filter `campaign.advertising_channel_type = 'PERFORMANCE_MAX'`), channel split via `segments.ad_network_type`, `segments.ad_using_product_data`, `segments.ad_using_video` (v23+); `asset_group` (ad strength, perf); `asset_group_asset` and `asset_group_top_combination_view` (assets); retail: `asset_group_product_group_view`, `shopping_performance_view`, `shopping_product`; locations: `location_view`; `campaign.feed_types` (`MERCHANT_CENTER_FEED` = retail, `TRAVEL_FEED`).
- **Placements**: `group_placement_view` (where ads showed; low-volume rows rolled into "Total: Other"), `detail_placement_view` (URLs / video IDs; high cardinality - filter by date and campaign), `managed_placement_view` (targeted placements), `performance_max_placement_view` (PMax; docs show only `metrics.impressions`; `segments.ad_network_type` v24+).
```sql
SELECT performance_max_placement_view.display_name, performance_max_placement_view.placement,
  performance_max_placement_view.placement_type, performance_max_placement_view.target_url, metrics.impressions
FROM performance_max_placement_view WHERE campaign.id = 123 AND segments.date DURING LAST_30_DAYS
```
- **Asset performance**: `ad_group_asset` / `campaign_asset` / `customer_asset` for asset-level metrics; `ad_group_ad_asset_view` for per-ad asset metrics + `performance_label` (`BEST, GOOD, LOW, LEARNING, PENDING`), `field_type`, `pinned_field`, `enabled` (RSA; v23+ also responsive display); `ad_group_ad_asset_combination_view` for served combinations.
```sql
SELECT ad_group_ad.ad.id, ad_group_ad_asset_view.field_type, ad_group_ad_asset_view.performance_label,
  asset.text_asset.text, metrics.impressions, metrics.clicks, metrics.conversions
FROM ad_group_ad_asset_view
WHERE ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD' AND ad_group_ad.status != 'REMOVED'
  AND ad_group_ad_asset_view.enabled = TRUE AND segments.date DURING LAST_30_DAYS
```
- **Keywords**: `keyword_view` + `ad_group_criterion.keyword.text` (text is not on the view). Criteria views join to their criterion (`keyword_view` -> `ad_group_criterion`; `location_view` -> `campaign_criterion`).
- **Locations**: `location_view` = performance of **targeted** location criteria (campaign_criterion). `geographic_view` = country-level rows by user physical location or area of interest (`location_type`); `user_location_view` = country-level by actual physical location with `targeting_location` true/false. Finer geo via `segments.geo_target_*` fields (check `selectable_with`).
- **Time of day / weekday**: segment by `segments.hour` (0-23) and/or `segments.day_of_week`; `segments.hour` is subject to the 37-month limit.
```sql
SELECT campaign.id, segments.day_of_week, segments.hour, metrics.clicks, metrics.conversions, metrics.cost_micros
FROM campaign WHERE segments.date DURING LAST_30_DAYS
```
- **Auction insights**: metrics `metrics.auction_insight_search_*` (with `segments.auction_insight_domain`) exist but the field reference says "This metric is **not publicly available**" - normal projects get an access-denied authorization error. Use `metrics.search_impression_share`, `search_budget_lost_impression_share`, `search_rank_lost_impression_share` instead.
- Conversion tracking status: `SELECT customer.conversion_tracking_setting.conversion_tracking_status, customer.conversion_tracking_setting.google_ads_conversion_customer FROM customer`.

Zdroj: https://developers.google.com/google-ads/api/docs/query/overview , https://developers.google.com/google-ads/api/docs/query/grammar , https://developers.google.com/google-ads/api/docs/query/structure , https://developers.google.com/google-ads/api/docs/query/date-ranges , https://developers.google.com/google-ads/api/docs/query/case-sensitivity , https://developers.google.com/google-ads/api/docs/query/ordering-limiting , https://developers.google.com/google-ads/api/docs/reporting/overview , https://developers.google.com/google-ads/api/docs/reporting/segmentation , https://developers.google.com/google-ads/api/docs/reporting/zero-metrics , https://developers.google.com/google-ads/api/docs/reporting/streaming , https://developers.google.com/google-ads/api/docs/reporting/paging , https://developers.google.com/google-ads/api/docs/reporting/uireports , https://developers.google.com/google-ads/api/docs/reporting/criteria-metrics , https://developers.google.com/google-ads/api/docs/reporting/placement-views , https://developers.google.com/google-ads/api/docs/change-event , https://developers.google.com/google-ads/api/docs/change-status , https://developers.google.com/google-ads/api/performance-max/reporting , https://developers.google.com/google-ads/api/performance-max/campaign-reporting , https://developers.google.com/google-ads/api/performance-max/campaign-criterion-reporting , https://developers.google.com/google-ads/api/docs/assets/fetching-assets , https://developers.google.com/google-ads/api/docs/responsive-search-ads/get-responsive-search-ads , https://developers.google.com/google-ads/api/reference/rpc/v25/CampaignSearchTermInsight , https://developers.google.com/google-ads/api/reference/rpc/v25/GeographicView , https://developers.google.com/google-ads/api/reference/rpc/v25/UserLocationView , https://developers.google.com/google-ads/api/fields/v25/metrics , https://developers.google.com/google-ads/api/docs/api-policy/rmf

---

## 4. Account management (MCC, settings, tracking, conversions)

### Headers and customer IDs
- `customer_id` in the request = operating account. Customer IDs always **without hyphens** (`CLIENT_CUSTOMER_ID_INVALID` otherwise).
- `login-customer-id` = the account through which the user is authorized; **required when access comes via a manager** (set to the manager ID), else `AuthorizationError.USER_PERMISSION_DENIED`. Defaults to the operating customer. Ignored by `ListAccessibleCustomers`.
- `linked-customer-id`: only for partner (e.g. app-analytics) access via product links.
- OAuth access tokens live 1 h. Cloud project in OAuth "Testing" status -> refresh tokens expire after 7 days (`invalid_grant`); publish the consent screen.
- `NOT_ADS_USER`: the Google account has no Google Ads access.

### Listing accounts and hierarchy
- `CustomerService.ListAccessibleCustomers`: no customer ID needed; returns only accounts the credentials can access **directly** (not those reachable only via a manager); canceled accounts not listed.
- Hierarchy: query `customer_client` from the manager (returns all transitive descendants; `customer_client.level` = depth; `customer_client.manager` bool). To build the tree, query `level <= 1` recursively per sub-manager; an account can have multiple managers - de-duplicate. Large recursive traversals can hit `RESOURCE_EXHAUSTED`.
- Canceled accounts: docs mention `customer_client.status = 'CANCELED'` filter (the listing page also says there's no direct way - verify). `CUSTOMER_NOT_ENABLED` = signup incomplete or deactivated (finish in UI).
- Accounts returning no hierarchy are typically test accounts or client accounts with incomplete billing (sample code comment).

### What can be done for MCC / manager accounts via API
- **Create client accounts**: `CustomerService.CreateCustomerClient` called with the **manager's** customer ID; required `descriptive_name`, `currency_code`, `time_zone`. Eligibility: manager must have **spent > USD 1,000** and be in policy good standing (`CustomerError.CREATION_DENIED_INELIGIBLE_MCC`, `CREATION_DENIED_FOR_POLICY_VIOLATION`). Optional `email_address` invites a user; `access_role` on create is **allowlist-only** - otherwise invite afterward. Errors: `ManagerLinkError.TOO_MANY_ACCOUNTS`, `TOO_MANY_ACCOUNTS_AT_MANAGER`, `MAX_DEPTH_EXCEEDED`, `CurrencyCodeError.UNSUPPORTED`, `TimeZoneError.INVALID_TIME_ZONE`. Needs Basic/Standard (not Explorer).
- **Link existing accounts**: (1) as manager, create `CustomerClientLink` with `status=PENDING` (`CustomerClientLinkService`); (2) as manager, query `customer_client_link.manager_link_id`; (3) as client, update `CustomerManagerLink` (`customers/{client}/customerManagerLinks/{manager}~{manager_link_id}`) to `ACTIVE` with update_mask. Linking needs credentials that can act as both sides (or two credential sets). Same link viewed from two sides.
- Limits: max 5 managers per account, depth 6, 20 pending manager invites per hierarchy.
- **Users**: invite via `CustomerUserAccessInvitationService` (users appear in `customer_user_access` only after accepting; pending in `customer_user_access_invitation`); change role (`update` with mask `access_role`) or remove via `CustomerUserAccessService` - caller must be `ADMIN`. Cannot remove/downgrade the last admin (`LAST_ADMIN_USER_OF_MANAGER`, `LAST_ADMIN_USER_OF_SERVING_CUSTOMER`). Role changes may create a **multi-party approval** request (`multi_party_auth_review` in result, `resource_name` empty) that a second admin resolves via `MultiPartyAuthReviewService.ResolveMultiPartyAuthReview`; pending changes are invisible to Search.
- Other account guides exist for product links (Merchant Center, data partners), YouTube linking and advertiser identity verification status/session start.
- Billing via API (`BillingSetupService`, `AccountBudgetProposalService`) only for **monthly invoicing** accounts, 1 op per request, 12 h spacing.

### Customer-level settings
- Customer is updated with `CustomerService.MutateCustomer` (single `operation`, no partial failure, not in batch jobs). Which Customer fields are mutable: see field behavior in the proto; guides document these account-level settings:
  - `tracking_url_template`, `final_url_suffix` (account level, overridden by lower levels).
  - `auto_tagging_enabled` - the guides do not have a dedicated auto-tagging page; field is on `Customer`. The offline-conversion guide requires GCLID capture (`gclid`/`gbraid`/`wbraid`), which depends on auto-tagging.
  - `conversion_tracking_setting.google_ads_conversion_customer` - switch to cross-account conversion tracking (request must come from the **new** conversion-manager MCC as `login-customer-id`).
- `currency_code` and `time_zone` are chosen at creation (guides give no way to change them).

### Tracking templates and URL parameters
- Fields: `final_urls`, `final_mobile_urls`, `final_app_urls`, `tracking_url_template`, `final_url_suffix`, `url_custom_parameters`. Settable at customer, campaign, ad group, ad, keyword/criterion and asset levels; **lower level overrides higher** (keyword > ad > ad group > campaign > customer).
- Tracking template is used instead of final URL to build the click URL; embed `{lpurl}`; landing page must match final URL. With **parallel tracking**, parameters the landing page needs must be in `final_url_suffix` or `final_urls`, not the tracking template.
- Custom parameters: max **8 per entity**, key <= **16 bytes**, alphanumeric; value <= **200 bytes**; reference as `{_key}`; keys case-insensitive (duplicate -> `DistinctError.DUPLICATE_ELEMENT`). ValueTrack nesting up to 4 levels.
- Final URL must not redirect off-domain. Changing only tracking (template/suffix/params) avoids ad re-review per overview page.

### Conversion tracking settings
- Check: `customer.conversion_tracking_setting.{google_ads_conversion_customer, conversion_tracking_status, conversion_tracking_id, cross_account_conversion_tracking_id}`. `google_ads_conversion_customer` = account that owns conversion actions (an MCC with cross-account tracking) - use it as `customer_id` when creating/managing conversion actions.
- `NOT_CONVERSION_TRACKED` -> enable by creating at least one `ConversionAction` in the conversion customer.
- Switching conversion manager has UI-equivalent side effects: adopts manager's default value rules and lifecycle goals; campaigns targeting specific actions switch to manager's default goals; an account can use actions from only one manager.
- Cross-account uploads allowed from the action owner's ancestors/descendants in the tree.
- ConversionAction defaults/rules: `counting_type` defaults `MANY_PER_CLICK`; attribution defaults `GOOGLE_SEARCH_ATTRIBUTION_DATA_DRIVEN`; only `GOOGLE_ADS_LAST_CLICK` and data-driven allowed (`CANNOT_SET_RULE_BASED_ATTRIBUTION_MODELS`); names unique (`DUPLICATE_NAME`); `type` and `app_id` immutable; `include_in_conversions_metric` cannot be set (`IMMUTABLE_FIELD`) - use `primary_for_goal`; click-through window 1-90 days (1-60 for `AD_CALL`/`WEBSITE_CALL`); view-through 1-30 days, not settable on call types; call types need `always_use_default_value=true`; enum `UNKNOWN` -> `INVALID_ENUM_VALUE`.
- `ConversionActionService` in cross-account setups also returns manager-owned actions, actions with accrued stats (even after unlink) and GA4 conversions not imported (status `HIDDEN`).
- Enhanced conversions sent via API are enabled automatically but can be disabled only in the UI.
- Consent for imported conversions/user data: set default consent in UI (Tools > Data Manager > Consent settings) or `consent` per payload.
- Offline click conversions: action type `UPLOAD_CLICKS`; `conversion_date_time` `yyyy-mm-dd HH:mm:ss+|-HH:mm`; `order_id` strongly recommended (reuse for adjustments); up to 5 user identifiers; **from 2026-06-15 `UploadClickConversions` fails for projects that never sent offline/enhanced conversion requests before** - Google points them to the Data Manager API.

### Things the guides say are UI-only or unavailable via the API
- The guides contain **no consolidated list** of UI-only account features. Explicitly documented gaps/restrictions found:
  - Scheduling and emailing reports; file download formats.
  - Auction insights metrics (not publicly available).
  - Completing account signup / reactivating (`CUSTOMER_NOT_ENABLED` -> UI).
  - Disabling enhanced conversions; account-level default consent settings (UI Data Manager).
  - Billing mutates for non-monthly-invoicing accounts.
  - `access_role` at account creation (allowlist), account creation by ineligible managers.
  - Google Ads Editor changes are not visible in `change_event`.
  - Access-level management happens in Google Cloud Console, not via API.

Zdroj: https://developers.google.com/google-ads/api/docs/concepts/call-structure , https://developers.google.com/google-ads/api/docs/account-management/overview , https://developers.google.com/google-ads/api/docs/account-management/create-account , https://developers.google.com/google-ads/api/docs/account-management/linking-manager-accounts , https://developers.google.com/google-ads/api/docs/account-management/listing-accounts , https://developers.google.com/google-ads/api/docs/account-management/get-account-hierarchy , https://developers.google.com/google-ads/api/docs/account-management/managing-users , https://developers.google.com/google-ads/api/docs/best-practices/common-errors , https://developers.google.com/google-ads/api/docs/ads/upgraded-urls/overview , https://developers.google.com/google-ads/api/docs/ads/upgraded-urls/fields , https://developers.google.com/google-ads/api/docs/conversions/getting-started , https://developers.google.com/google-ads/api/docs/conversions/upload-offline , https://developers.google.com/google-ads/api/docs/targeting/location-targeting , https://developers.google.com/google-ads/api/docs/reporting/uireports , https://developers.google.com/google-ads/api/docs/best-practices/quotas

# Google Ads API v25 - Campaigns, budgets, bidding, ads, targeting (guide knowledge)

Scope: rules, requirements, workflows and gotchas from the official guides (developers.google.com/google-ads/api, pages last updated Sep-Oct 2026). Field lists are intentionally omitted (use the proto reference). Where a guide is silent, this file says so. JSON examples are `GoogleAdsService.Mutate` `MutateOperation` objects in snake_case; customer ID `1234567890` is a placeholder; int64 micros may be sent as JSON strings or numbers.

---

## 1. Creating campaigns per type

### General rules (all types)
- Required on every `Campaign` create: `name`, `status`, `advertising_channel_type`, `campaign_budget`, a bidding strategy (either the `campaign_bidding_strategy` oneof, e.g. `maximize_conversions`, or a portfolio `bidding_strategy` resource name - never both), and `contains_eu_political_advertising` (see below).
- `bidding_strategy_type` is read-only (output). Set the scheme oneof instead; sending `bidding_strategy_type` is ignored.
- There is no "objective" field. The UI objective wizard (Sales/Leads...) does not exist in the API; you assemble channel type + bidding + conversion goals yourself.
- `advertising_channel_sub_type`: leave unset for standard SEARCH, DISPLAY, PERFORMANCE_MAX, DEMAND_GEN. Set it only for special variants (PMax `TRAVEL_GOALS`, Shopping `SHOPPING_COMPARISON_LISTING_ADS`, App `APP_CAMPAIGN*`).
- A Search campaign created via API always appears as "All features" subtype in the UI.
- Create new campaigns `PAUSED`; enable after targeting and ads exist (all official samples do this).
- Dates: `start_date_time` / `end_date_time`, format `yyyy-MM-dd HH:mm:ss`, in the account time zone. Optional except when using a campaign total budget (end date mandatory).
- Atomic creation: send all operations in one `GoogleAdsService.Mutate` (atomic unless `partial_failure=true`), using negative temporary IDs in resource names (`customers/1234567890/campaignBudgets/-1`). Temp IDs are valid only inside that one request; order operations so a resource is created before anything references it (budget -> campaign -> criteria/ad group -> assets -> ads/asset links).
- Campaign groups (`CampaignGroupService`): a campaign can be in only one group; campaigns with shared budgets cannot be added; performance targets are not supported in the API.
- Display Expansion on Search = Search campaign with `network_settings.target_content_network = true`.

### EU political advertising declaration (`contains_eu_political_advertising`)
- Values: `CONTAINS_EU_POLITICAL_ADVERTISING`, `DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING` (`UNSPECIFIED` = undeclared).
- Creating a campaign without it fails with `FieldError.REQUIRED` (applies to `CampaignService`, `GoogleAdsService.Mutate`, batch jobs).
- Existing undeclared campaigns: creating/updating `location`, `proximity` or `location_group` criteria (campaign or ad group level) fails with `CriterionError.MISSING_EU_POLITICAL_ADVERTISING_SELF_DECLARATION`.
- Since 2026-04-01: if ANY campaign in the account is undeclared, practically all campaign-management mutate methods (campaigns, ad groups, ads, assets, criteria, budgets, bidding, shared sets, user lists, conversions, recommendations apply, experiments...) fail with `MutateError.EU_POLITICAL_ADVERTISING_DECLARATION_REQUIRED`. Reporting, account management and Keyword Planner keep working.
- Fix: query undeclared campaigns and update ONLY `contains_eu_political_advertising` (that update is allowed despite the account-level block). Account-level status readable via `customer.contains_eu_political_advertising`.
- `CONTAINS_EU_POLITICAL_ADVERTISING` -> campaign stops serving in the EU.
- Experiments: `ExperimentService.ScheduleExperiment` fails with `ExperimentError.MISSING_EU_POLITICAL_ADVERTISING_SELF_DECLARATION` if treatment draft campaigns are undeclared.

### Search
- Minimum valid serving set: `CampaignBudget`, `Campaign` (`SEARCH`), `AdGroup` (type `SEARCH_STANDARD`), `AdGroupCriterion` keywords, `AdGroupAd` with RSA. Location/language criteria are optional but practically required.
- `network_settings`: `target_google_search`, `target_search_network` (partners), `target_content_network` (Display Expansion), `target_partner_search_network` (sample sets false).
- AI Max for Search is not a campaign type, it is a setting on a Search campaign (see section 4).
- Example (one atomic request):
```json
[
 {"campaign_budget_operation":{"create":{"resource_name":"customers/1234567890/campaignBudgets/-1","name":"Search budget 1","amount_micros":50000000,"delivery_method":"STANDARD","explicitly_shared":false}}},
 {"campaign_operation":{"create":{"resource_name":"customers/1234567890/campaigns/-2","name":"Search - brand","status":"PAUSED","advertising_channel_type":"SEARCH","campaign_budget":"customers/1234567890/campaignBudgets/-1","maximize_conversions":{"target_cpa_micros":20000000},"network_settings":{"target_google_search":true,"target_search_network":false,"target_content_network":false,"target_partner_search_network":false},"geo_target_type_setting":{"positive_geo_target_type":"PRESENCE"},"contains_eu_political_advertising":"DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"}}},
 {"campaign_criterion_operation":{"create":{"campaign":"customers/1234567890/campaigns/-2","location":{"geo_target_constant":"geoTargetConstants/21167"}}}},
 {"campaign_criterion_operation":{"create":{"campaign":"customers/1234567890/campaigns/-2","language":{"language_constant":"languageConstants/1000"}}}},
 {"ad_group_operation":{"create":{"resource_name":"customers/1234567890/adGroups/-3","name":"Brand exact","campaign":"customers/1234567890/campaigns/-2","type":"SEARCH_STANDARD","status":"ENABLED"}}},
 {"ad_group_criterion_operation":{"create":{"ad_group":"customers/1234567890/adGroups/-3","status":"ENABLED","keyword":{"text":"acme shoes","match_type":"PHRASE"}}}},
 {"ad_group_ad_operation":{"create":{"ad_group":"customers/1234567890/adGroups/-3","status":"ENABLED","ad":{"final_urls":["https://www.example.com"],"responsive_search_ad":{"headlines":[{"text":"Acme Shoes","pinned_field":"HEADLINE_1"},{"text":"Free Returns"},{"text":"Shop New Arrivals"}],"descriptions":[{"text":"Comfortable shoes for every day."},{"text":"Order online, delivered fast."}],"path1":"shoes"}}}}}
]
```

### Performance Max (standard = online sales / lead gen)
- `advertising_channel_type = PERFORMANCE_MAX`, no sub-type (`TRAVEL_GOALS` only for travel).
- Required resources for a serving campaign: `CampaignBudget`, `Campaign`, `CampaignAsset`s (only when brand guidelines enabled), `AssetGroup`(s), `AssetGroupAsset`s (+ the `Asset`s). Not all must be in one request, but:
  - `AssetGroup` + its `AssetGroupAsset`s that satisfy the minimum asset requirements MUST be in one atomic request. Do not create a non-retail asset group with `AssetGroupService` alone.
  - With brand guidelines enabled, `Campaign` + its required `CampaignAsset`s MUST be in one request, without partial failure.
  - `AssetGroupSignal`s can be in the same or a later request.
- Ordering inside the bulk mutate: all `AssetOperation`s before all `AssetGroupAssetOperation`s; do not interleave them. The server checks minimum asset requirements after each consecutive run of asset-group-asset ops; a failed check rejects the whole request.
- Budget: must NOT be shared (`explicitly_shared=false`); period `DAILY` (or `CUSTOM_PERIOD` for a campaign total budget with start+end dates). Guide recommends daily budget >= 3x target CPA / cost per conversion.
- Bidding: only `maximize_conversions` (optional `target_cpa_micros`) or `maximize_conversion_value` (optional `target_roas`), set directly on the campaign. Portfolio strategies are NOT supported for PMax (PMax guides). Note: the generic strategy-types table says MAXIMIZE_CONVERSIONS portfolio "can be used with ... Performance Max" - conflicting; follow the PMax guide (standard only).
- Invalid state vs invalid request: a campaign without an asset group is accepted but does not serve; an asset group without its minimum assets is rejected.
- Limits: max 100 PMax campaigns per account (`ResourceCountLimitExceededError.ACCOUNT_LIMIT`), 1-100 asset groups per campaign, asset groups cannot be shared between campaigns.
- Asset groups: at least one `final_urls` entry; a final URL of the asset group cannot be excluded via `WEBPAGE` campaign criteria. `AssetGroupOperation` must be atomic (no partial failure) and cannot be used in `BatchJobService` (use `GoogleAdsService.Mutate`); `AssetGroupAssetOperation` can be used in batch jobs.
- Updates: a request that would leave an asset group below the minimums (e.g. removing a required asset) fails. Prefer adding new assets over removing weak ones until max counts are reached.

#### PMax asset group minimum assets (non-retail create, and ANY asset update on any asset group)
| AssetFieldType | Limit | Min | Max |
|---|---|---|---|
| `HEADLINE` | 30 chars | 3 | 15 |
| `LONG_HEADLINE` | 90 chars | 1 | 5 |
| `DESCRIPTION` | 90 chars | 2 | 5 |
| `MARKETING_IMAGE` | 1.91:1, rec 1200x628, min 600x314, <=5120 KB | 1 | 20 |
| `SQUARE_MARKETING_IMAGE` | 1:1, rec 1200x1200, min 300x300, <=5120 KB | 1 | 20 |
| `BUSINESS_NAME` (only if brand guidelines disabled) | 25 chars | 1 | 1 |
| `LOGO` (only if brand guidelines disabled) | 1:1, rec 1200x1200, min 128x128, <=5120 KB | 1 | 5 |
- Optional: `PORTRAIT_MARKETING_IMAGE` 4:5 (rec 960x1200, min 480x600) max 20; `LANDSCAPE_LOGO` 4:1 (rec 1200x300, min 512x128) max 20; `YOUTUBE_VIDEO` 16:9, 1:1 or 9:16, >= 10 s, max 15; `CALL_TO_ACTION_SELECTION` max 1; `MEDIA_BUNDLE` < 150 KB max 1.
- Aspect ratio is validated when LINKING (`ASPECT_RATIO_NOT_ALLOWED`), not when uploading the asset.
- Uploading an image whose content already exists under another name silently keeps the old name.
- Ad strength / coverage: `asset_group.asset_coverage.ad_strength_action_items`; if an action item asks for VIDEO and `AssetCoverageVideoAspectRatioRequirement` is unset, any YouTube video can be linked.

#### PMax brand guidelines
- Enabled by default for new standard and retail PMax campaigns (v21+). Opt out with `brand_guidelines_enabled=false`. Not supported for travel goals. A dedicated method `CampaignService.EnablePMaxBrandGuidelines` exists for enabling brand guidelines on existing campaigns (listed among enforced mutate methods; its workflow is not described in the fetched guides).
- Enabled: link brand assets at campaign level via `CampaignAsset`: exactly 1 `BUSINESS_NAME`, >= 1 `LOGO`, plus up to 4 optional `LOGO`/`LANDSCAPE_LOGO`; all in the campaign creation request, no partial failure. Retail campaigns with no `AssetGroupAsset`s are exempt.
- Disabled: link `BUSINESS_NAME` and `LOGO` to each asset group via `AssetGroupAsset` instead.
- Optional `brand_guidelines.main_color` + `accent_color` (hex, both or neither) and `predefined_font_family` (case-sensitive: Open Sans, Roboto, Montserrat, Poppins, Lato, Oswald, Playfair Display, Roboto Slab).
- `text_guidelines`: `term_exclusions`, `messaging_restrictions`.

#### PMax final URL expansion, text customization, asset automation
- URL expansion is ON by default. Since v22 controlled by `Campaign.asset_automation_settings` entry `FINAL_URL_EXPANSION_TEXT_ASSET_AUTOMATION` (`OPTED_IN`/`OPTED_OUT`); `Campaign.url_expansion_opt_out` is the pre-v22 mechanism.
- While URL expansion is on, text customization is on and cannot be opted out. `TEXT_ASSET_AUTOMATION` controls text customization independently when expansion does not occur.
- Exclude URLs from expansion with negative `WEBPAGE` campaign criteria. Generated text assets: `final_url_expansion_asset_view`; remove with `AutomaticallyCreatedAssetRemovalService`.
- Other automation types used in samples: image extraction, image enhancement, enhanced YouTube video generation. Google recommends opting in to all.

#### PMax campaign criteria
- Supported: `AD_SCHEDULE`, `AGE_RANGE`, `DEVICE`, `LANGUAGE` (validated against campaign country; `CANNOT_TARGET_LANGUAGE`), `LOCATION`, `LOCATION_GROUP`, `WEBPAGE` (negative = URL-expansion exclusion), `BRAND` (negative only = brand exclusion), `KEYWORD` (negative only, max 10,000 per campaign), campaign-level gender exclusion.
- No location criterion = all regions. Local Services PMax must keep >= 1 positive location (`CANNOT_REMOVE_ALL_LOCATIONS_FROM_LOCAL_SERVICES_PMAX_CAMPAIGN`).

#### PMax asset group signals (`AssetGroupSignal`)
- One signal per `AssetGroupSignal` (oneof): `audience` (an `Audience` resource), `search_theme` (`SearchThemeInfo.text`), `local_services_id` (allowlisted GLS PMax only).
- Create/remove only, never update. To change an audience signal, update the `Audience` via `AudienceService`.
- `Audience` scope `ASSET_GROUP` requires `Audience.asset_group` (set iff scope is ASSET_GROUP); upgrading to `CUSTOMER` scope clears it.
- Standard PMax can run without signals; GLS PMax needs >= 1 (`CANNOT_REMOVE_ALL_SIGNALS`).
- Search theme count/length limits are NOT stated in the API guides.

#### PMax retail (product feed) and listing groups
- Google Ads account must be linked to Merchant Center. Set `Campaign.shopping_setting.merchant_id` (required); optional `feed_label` (replaces deprecated `sales_country`; a country code in feed_label does not create geo targeting), `campaign_priority`, `enable_local`. Vehicle ads: `Campaign.listing_type = VEHICLES`.
- Minimum retail resources: budget, campaign with shopping_setting, `AssetGroup`, `AssetGroupListingGroupFilter`. Asset group `final_urls` must belong to the Merchant Center account's site.
- Retail asset group asset state is binary: no assets at all, or full minimum set. Linking any asset activates all requirements, so all required assets must be added in one request; no incremental adds.
- Every retail asset group needs a valid listing group tree; minimal tree = single root `UNIT_INCLUDED` (all products).
- Tree rules (`AssetGroupListingGroupFilter`): `listing_source = SHOPPING`; `type` = `SUBDIVISION` / `UNIT_INCLUDED` / `UNIT_EXCLUDED`; root has no `parent_listing_group_filter` and no `case_value`; each subdivision must be fully partitioned, i.e. created in the same request with >= 1 child AND an "Other" node (empty dimension message, e.g. `"case_value":{"product_brand":{}}`); siblings must use the same dimension type; parents before children in the request; temp IDs for parents.
- Removal: children before parents (else error). Adding a second root fails with `ASSET_GROUP_LISTING_GROUP_FILTER_ERROR_MULTIPLE_ROOTS` -> to replace a tree, remove the old nodes (children first) and create the new tree in the same request.
- Dimensions: `ProductBrandInfo`, `ProductCategoryInfo`, `ProductChannelInfo`, `ProductConditionInfo`, `ProductCustomAttributeInfo`, `ProductItemIdInfo`, `ProductTypeInfo`. Prefer groups (brand, custom labels) over item IDs.
- Limits: 1,000 listing group filters per asset group; max subdivision depth 7 (`AssetGroupListingGroupFilterError.TREE_TOO_DEEP`).
```json
[
 {"asset_group_listing_group_filter_operation":{"create":{"resource_name":"customers/1234567890/assetGroupListingGroupFilters/111~-1","asset_group":"customers/1234567890/assetGroups/111","type":"SUBDIVISION","listing_source":"SHOPPING"}}},
 {"asset_group_listing_group_filter_operation":{"create":{"resource_name":"customers/1234567890/assetGroupListingGroupFilters/111~-2","asset_group":"customers/1234567890/assetGroups/111","parent_listing_group_filter":"customers/1234567890/assetGroupListingGroupFilters/111~-1","type":"UNIT_INCLUDED","listing_source":"SHOPPING","case_value":{"product_brand":{"value":"CoolBrand"}}}}},
 {"asset_group_listing_group_filter_operation":{"create":{"resource_name":"customers/1234567890/assetGroupListingGroupFilters/111~-3","asset_group":"customers/1234567890/assetGroups/111","parent_listing_group_filter":"customers/1234567890/assetGroupListingGroupFilters/111~-1","type":"UNIT_EXCLUDED","listing_source":"SHOPPING","case_value":{"product_brand":{}}}}}
]
```

#### PMax standard - minimal atomic create (brand guidelines enabled)
```json
[
 {"campaign_budget_operation":{"create":{"resource_name":"customers/1234567890/campaignBudgets/-1","name":"PMax budget","amount_micros":100000000,"delivery_method":"STANDARD","explicitly_shared":false}}},
 {"campaign_operation":{"create":{"resource_name":"customers/1234567890/campaigns/-2","name":"PMax leads","status":"PAUSED","advertising_channel_type":"PERFORMANCE_MAX","campaign_budget":"customers/1234567890/campaignBudgets/-1","maximize_conversion_value":{"target_roas":3.5},"brand_guidelines_enabled":true,"contains_eu_political_advertising":"DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"}}},
 {"asset_operation":{"create":{"resource_name":"customers/1234567890/assets/-10","text_asset":{"text":"Acme"}}}},
 {"asset_operation":{"create":{"resource_name":"customers/1234567890/assets/-11","name":"Logo 1:1","image_asset":{"data":"<base64>"}}}},
 {"campaign_asset_operation":{"create":{"campaign":"customers/1234567890/campaigns/-2","asset":"customers/1234567890/assets/-10","field_type":"BUSINESS_NAME"}}},
 {"campaign_asset_operation":{"create":{"campaign":"customers/1234567890/campaigns/-2","asset":"customers/1234567890/assets/-11","field_type":"LOGO"}}},
 {"asset_group_operation":{"create":{"resource_name":"customers/1234567890/assetGroups/-3","name":"AG 1","campaign":"customers/1234567890/campaigns/-2","final_urls":["https://www.example.com"],"status":"PAUSED"}}},
 "... asset_operation creates for 3+ HEADLINE, 1+ LONG_HEADLINE, 2+ DESCRIPTION text assets, 1+ MARKETING_IMAGE, 1+ SQUARE_MARKETING_IMAGE image assets (all asset_operation BEFORE any asset_group_asset_operation) ...",
 {"asset_group_asset_operation":{"create":{"asset_group":"customers/1234567890/assetGroups/-3","asset":"customers/1234567890/assets/-20","field_type":"HEADLINE"}}},
 {"asset_group_signal_operation":{"create":{"asset_group":"customers/1234567890/assetGroups/-3","search_theme":{"text":"running shoes"}}}}
]
```

#### New Customer Acquisition (NCA) and lifecycle goals (v25 unified schema)
- Account level: create a `Goal` via `GoalService` with `goal_type = NEW_CUSTOMER_ACQUISITION` and `new_customer_acquisition_goal_settings.value_settings` (`additional_value`; optional `additional_high_lifetime_value` which must be > value). `value_multiplier` is not supported for NCA (only `LOYALTY_RETENTION`); `high_lifetime_value_multiplier` "not supported yet". Max one Goal per type per account (`GoalError.NEW_CUSTOMER_ACQUISITION_GOAL_ALREADY_EXISTS`). Other types: `CUSTOMER_RETENTION` (needs PMax + Customer Match list), `LOYALTY_RETENTION`.
- Campaign level: `CampaignGoalConfig` (`CampaignGoalConfigService.MutateCampaignGoalConfigs`) with `campaign`, `goal` and `campaign_new_customer_acquisition_settings.target_option`: `TARGET_ALL` (bid higher for new customers) or `TARGET_SPECIFIC` (new customers only; then no value overrides allowed -> `CAMPAIGN_OVERRIDE_VALUES_SET_FOR_NEW_CUSTOMER_ACQUISITION_TARGET_SPECIFIC_OPTION`). Optional `value_settings_override`.
- Existing customers must be defined with `UserListCustomerType` (create/remove only) linking user lists to categories (`PURCHASERS`, `CONVERTED_LEADS`, `QUALIFIED_LEADS`, `CART_ABANDONERS`, `DISENGAGED_CUSTOMERS`, loyalty tiers); conflicting pairs (e.g. PURCHASERS + CONVERTED_LEADS on the same list) -> `CONFLICTING_CUSTOMER_TYPES`.
- Incompatible combos -> `CampaignGoalConfigError.CANNOT_USE_INCOMPATIBLE_CLO_GOALS` (e.g. NCA any mode + Retention TARGET_SPECIFIC; NCA TARGET_SPECIFIC + Retention TARGET_ALL; Prospecting + NCA).
- With cross-account conversion tracking, customer-level goals go into the conversion (manager) account; campaign configs stay in the client account.

### Demand Gen
- `advertising_channel_type = DEMAND_GEN`, no sub-type. Set up conversion goals first.
- Budget must NOT be shared. Minimum daily budget 5 USD equivalent (`CampaignBudgetError.BUDGET_BELOW_PER_DAY_MINIMUM`, minimum returned in `ErrorDetails.budget_per_day_minimum_error_details.minimum_budget_amount_micros`). Guide recommends daily budget >= 15x target CPA. Total budget: `total_amount_micros` + period `CUSTOM_PERIOD` (guide text says "CUSTOM") + campaign start/end.
- Bidding: Maximize clicks (`target_spend`), Target CPA, Maximize conversions, Target ROAS; also `TARGET_CPC` via `Campaign.target_cpc` (ad group override `target_cpc_micros`). The budgets page additionally lists Maximize conversion value and Manual CPC as compatible with Demand Gen total budgets.
- Order: budget -> campaign -> ad group (NO `type`) -> audience criteria -> assets -> ads, all in one atomic mutate with temp IDs recommended.
- Ad group: targeting (audiences, location, language, listing groups) lives at AD GROUP level via `AdGroupCriterion` (location guide: ad-group-level location for Demand Gen with `upgraded_targeting`). Audience targeting requires `audience_setting.use_audience_grouped = true` at ad group creation (immutable).
- Channel controls: `AdGroup.demand_gen_ad_group_settings.channel_controls` oneof: `channel_strategy` (`ALL_CHANNELS` default, `ALL_OWNED_AND_OPERATED_CHANNELS` = no GDN) OR `selected_channels` booleans (`youtube_in_stream`, `youtube_in_feed`, `youtube_shorts`, `discover`, `gmail`, `display`, `maps` (v24+)). When updating selected_channels set every flag explicitly.
- Ads: `DemandGenMultiAssetAdInfo` (supports `classic_display_images`; v25+ auto-opts into `GENERATE_ANIMATED_IMAGES_FROM_OTHER_ASSETS`, opt out via `AdGroupAd.ad_group_ad_asset_automation_settings`), `DemandGenCarouselAdInfo`, `DemandGenVideoResponsiveAdInfo` (requires `business_name`; v24+ also `videos` and `logo_images`; auto-opts into `GENERATE_LANDING_PAGE_TEXT`), `DemandGenProductAdInfo`. All are mutable.
- Product feed: link Merchant Center, `Campaign.shopping_setting.merchant_id` (+ optional `feed_label`), ad-group `ListingGroupInfo` tree (root `UNIT` or `SUBDIVISION`; Google recommends at least one root listing group per product ad group).
- Lookalike segments are available only in Demand Gen.

### Standard Shopping
- Prerequisite: Google Ads account linked to Merchant Center.
- `advertising_channel_type = SHOPPING`; `shopping_setting.merchant_id` (required) and `campaign_priority` (required for standard Shopping, 0-2, higher wins); optional `feed_label`, `enable_local`, `ignore_brand_exclusion_in_shopping_ads` (v24.2+), `advertising_partner_ids` (immutable).
- `network_settings.target_content_network = true` -> `CampaignError.CANNOT_TARGET_CONTENT_NETWORK`.
- Bidding: standard (campaign) `manual_cpc`, `target_spend`, `target_roas`, `maximize_conversion_value`; portfolio `target_spend`, `target_roas`, `maximize_conversion_value`, `maximize_conversions` (as listed in the Shopping guide). Shared budgets allowed.
- Ad group type `SHOPPING_PRODUCT_ADS`; >= 1 ad (`ShoppingProductAdInfo`, not mutable) per ad group; a listing group tree (`AdGroupCriterion.listing_group`) is required to serve.
- Listing tree (ad group level): subdivisions must be fully partitioned (include "Other"); bids only on positive `UNIT` nodes and REQUIRED there when bidding is manual (`cpc_bid_micros`); no bids on `SUBDIVISION` or negative nodes; >= 1 unit node (root may be the single unit). Max 20,000 listing groups per ad group. A single request may modify the tree structure of at most 2 Shopping ad groups (`OPERATIONS_FOR_TOO_MANY_SHOPPING_ADGROUPS`; use batch jobs for more).
- Comparison Listing (CSS only): sub-type `SHOPPING_COMPARISON_LISTING_ADS`, CSS merchant_id, `manual_cpc` only, ad group type `SHOPPING_COMPARISON_LISTING_ADS`, listing tree required.
- Smart Shopping is gone (upgraded to PMax).

### Display
- No dedicated "create Display campaign" guide; use `advertising_channel_type = DISPLAY`, ad groups with responsive display ads.
- Responsive display ad required fields: `marketing_images`, `square_marketing_images`, `headlines`, `long_headline`, `descriptions`, `business_name`, plus `Ad.final_urls`. Images must be uploaded as assets first. `format_setting = NATIVE` is not allowed when `allow_flexible_color = false`.
- `MANUAL_CPM` works only for Display-network-only campaigns (Search -> `OPERATION_NOT_PERMITTED_FOR_CAMPAIGN_TYPE`).
- Smart Display campaigns can no longer be created (use standard Display or PMax).

### Video (YouTube) - what is NOT supported
- Video campaigns, ad groups, ads and criteria are read/report-only: you cannot create, pause, enable, change targeting or add ads through the API. Use the UI or Google Ads scripts, or use Demand Gen / PMax for API-managed video.
- Exceptions: `VideoResponsiveAdInfo` is mutable since v24 (`videos`, `business_name`, `logo_images` required); Video experiments `YOUTUBE_CUSTOM` via `experiment.video_experiment` (v24+). `VideoAd` is reporting-only. `campaign.video_brand_safety_suitability` removed in v24 (use `customer.video_brand_safety_suitability`).

### App campaigns
- `advertising_channel_type = MULTI_CHANNEL`; sub-type `APP_CAMPAIGN` / `APP_CAMPAIGN_FOR_ENGAGEMENT` / `APP_CAMPAIGN_FOR_PRE_REGISTRATION`; `app_campaign_setting.app_id` (Play package name or numeric App Store ID), `app_store`, `bidding_strategy_goal_type`.
- Budget must not be shared. Portfolio strategies not allowed; bidding must be set at creation: `target_cpa` (target install/conversion cost), `target_roas`, `maximize_conversions`, `maximize_conversion_value` - according to `bidding_strategy_goal_type` (e.g. `OPTIMIZE_INSTALLS_TARGET_INSTALL_COST` -> `target_cpa`; `OPTIMIZE_RETURN_ON_ADVERTISING_SPEND` -> `target_roas`, Firebase conversions required; pre-registration -> `OPTIMIZE_PRE_REGISTRATION_CONVERSION_VOLUME` + `target_cpa`, `optimization_goal_setting.optimization_goal_types` must include `APP_PRE_REGISTRATION`).
- Conversion optimization only through `selective_optimization.conversion_actions` (required for engagement and in-app-action/tROAS goals); App campaigns do not use `CampaignConversionGoal`. Pre-registration `selective_optimization` is immutable/automatic.
- Targeting: campaign criteria only location and language; keyword exclusions only via `NEGATIVE_KEYWORDS` shared set + `CampaignSharedSet`.
- Ad groups: no `type`; no ad-group or criterion-level bid overrides (except optional `target_cpa_micros` for engagement); no negative ad group criteria; engagement campaigns must target a `UserList`. Ad info per sub-type: `AppAdInfo` / `AppEngagementAdInfo` / `AppPreRegistrationAdInfo`. Text assets can be created inline; other assets must be referenced by resource name. API-structure guide: App campaigns can have only one ad group ad per ad group.
- `view_through_conversion_optimization_enabled` (v24+) only for Android `APP_CAMPAIGN`.

### Smart campaigns
- Creation is unsupported from 2026-09-23: v24.2/v25 return `SmartCampaignError.CREATION_FAILED` (older: `AuthorizationError.ACTION_NOT_PERMITTED`). Existing Smart campaigns keep serving and remain updatable/reportable.
- Migration: `SmartCampaignSettingService.GeneratePMaxDraftCampaign` (v25.2+).
- Constraints for existing ones: one ad group per campaign; budget not shareable; `SmartCampaignSetting` must be created in the same Mutate as the campaign; ads 3-15 headlines, 2-4 descriptions.

### Other deprecations relevant to creation
- Call-only ads: `CallAd` removed in v23; existing call-only ads supported until Feb 2027 -> use RSA + call assets.
- Expanded text ads / text ads: cannot be created or edited (ETAs can only be paused/removed).
- Local campaigns and Smart Shopping -> PMax.

Zdroj: https://developers.google.com/google-ads/api/docs/campaigns/overview, https://developers.google.com/google-ads/api/docs/campaigns/create-campaigns, https://developers.google.com/google-ads/api/docs/campaigns/search-campaigns/getting-started, https://developers.google.com/google-ads/api/docs/api-policy/eu-par, https://developers.google.com/google-ads/api/performance-max/getting-started, https://developers.google.com/google-ads/api/performance-max/create-campaign, https://developers.google.com/google-ads/api/performance-max/create-budget, https://developers.google.com/google-ads/api/performance-max/asset-requirements, https://developers.google.com/google-ads/api/performance-max/asset-groups, https://developers.google.com/google-ads/api/performance-max/structure-requests, https://developers.google.com/google-ads/api/performance-max/asset-group-signals, https://developers.google.com/google-ads/api/performance-max/create-campaign-criteria, https://developers.google.com/google-ads/api/performance-max/optimizations, https://developers.google.com/google-ads/api/performance-max/retail, https://developers.google.com/google-ads/api/performance-max/listing-groups, https://developers.google.com/google-ads/api/samples/add-performance-max-product-listing-group-tree, https://developers.google.com/google-ads/api/docs/conversions/goals/lifecycle-goals, https://developers.google.com/google-ads/api/docs/demand-gen/overview, https://developers.google.com/google-ads/api/docs/demand-gen/create-campaign, https://developers.google.com/google-ads/api/docs/demand-gen/channel-controls, https://developers.google.com/google-ads/api/docs/demand-gen/product-ads, https://developers.google.com/google-ads/api/docs/shopping-ads/create-campaign, https://developers.google.com/google-ads/api/docs/shopping-ads/create-ad-group, https://developers.google.com/google-ads/api/docs/responsive-display-ads/create-responsive-display-ads, https://developers.google.com/google-ads/api/docs/video/overview, https://developers.google.com/google-ads/api/docs/app-campaigns/create-campaign, https://developers.google.com/google-ads/api/docs/app-campaigns/create-ad-group, https://developers.google.com/google-ads/api/docs/smart-campaigns/overview, https://developers.google.com/google-ads/api/docs/best-practices/system-limits

---

## 2. Budgets

### Types
- Average daily budget: `amount_micros`, `period = DAILY` (default). Spend can vary per day; monthly spend capped at daily x 30.4.
- Campaign total budget: `total_amount_micros`, `period = CUSTOM_PERIOD`, `explicitly_shared = false` (total budgets can never be shared). Only for Demand Gen, Search, Standard Shopping, PMax and YouTube campaigns that have both `start_date_time` and `end_date_time`. Missing end date -> `CampaignError.END_DATE_TIME_REQUIRED_FOR_TOTAL_BUDGET`; too long -> `CampaignError.DURATION_TOO_LONG_FOR_TOTAL_BUDGET`.
- Budget type (daily vs total) cannot be changed after campaign creation.
- Strategies compatible with total budgets: Search - tROAS, Max conv value, tCPA, Max conv, Max clicks, Target impression share, Manual CPC; PMax - tROAS, Max conv value, tCPA, Max conv; Shopping - tROAS, Max clicks, Manual CPC; Demand Gen - Max conv, tCPA, Max conv value, tROAS, Max clicks, Target CPC, Manual CPC; Video (read-only) - tCPM, tCPV.

### Shared vs non-shared
- `explicitly_shared` defaults to `true` on create when omitted -> to make a single-campaign budget you MUST send `explicitly_shared: false`.
- `true -> false` is impossible (`CampaignBudgetError.CANNOT_UPDATE_CAMPAIGN_BUDGET_TO_IMPLICITLY_SHARED`). `false -> true` allowed only if no experiments run on the campaign.
- Must be non-shared: PMax, App, Demand Gen, Smart campaigns, campaigns with experiments (`CampaignError.CAMPAIGN_CANNOT_USE_SHARED_BUDGET`). Campaigns with shared budgets cannot join campaign groups.
- Shared budgets appear in the UI Shared Library; non-shared only in campaign settings. Check with `SELECT campaign_budget.explicitly_shared FROM campaign_budget WHERE campaign_budget.id = X`.
- Limits: 11,000 shared and 20,000 unshared budgets per account (`ResourceCountLimitExceededError.ACCOUNT_LIMIT`); no limit on campaigns per shared budget.

### Delivery method
- All guide samples use `delivery_method = STANDARD`; the guides do not describe other delivery methods. Use STANDARD.

### Other rules
- Remove: a budget attached to enabled or paused campaigns cannot be removed (`CampaignBudgetError.CAMPAIGN_BUDGET_IN_USE`).
- Portfolio alignment: an existing shared budget and an existing portfolio strategy can be aligned (`BiddingStrategy.aligned_campaign_budget_id` <-> `CampaignBudget.aligned_bidding_strategy_id`). They must reference each other, cover exactly the same set of campaigns, previous partners cleared in the same transaction, all in a single `GoogleAdsService.Mutate`. Cannot create both and align in one step.
- Budget recommendations: `CAMPAIGN_BUDGET`, `MOVE_UNUSED_BUDGET`, `MARGINAL_ROI_CAMPAIGN_BUDGET`, `FORECASTING_CAMPAIGN_BUDGET`.
```json
{"campaign_budget_operation":{"create":{"resource_name":"customers/1234567890/campaignBudgets/-1","name":"Promo total","total_amount_micros":3000000000,"period":"CUSTOM_PERIOD","delivery_method":"STANDARD","explicitly_shared":false}}}
```
(campaign must then have `start_date_time` and `end_date_time`).

Zdroj: https://developers.google.com/google-ads/api/docs/campaigns/budgets/overview, https://developers.google.com/google-ads/api/docs/campaigns/budgets/create-budgets, https://developers.google.com/google-ads/api/docs/campaigns/budgets/share-budgets, https://developers.google.com/google-ads/api/docs/campaigns/budgets/restrictions-errors, https://developers.google.com/google-ads/api/docs/campaigns/bidding/assign-strategies, https://developers.google.com/google-ads/api/docs/best-practices/system-limits

---

## 3. Bidding

### Standard vs portfolio
- Standard: set the scheme in the campaign's `campaign_bidding_strategy` oneof; do NOT set `Campaign.bidding_strategy`.
- Portfolio: create `BiddingStrategy` (`name` + scheme) via `BiddingStrategyService`, then set `Campaign.bidding_strategy` to its resource name. Cross-account portfolio strategies can be owned by a manager account (separate guide).
- Wrong context errors: portfolio-only scheme as standard -> `BiddingError.INVALID_ANONYMOUS_BIDDING_STRATEGY_TYPE`; standard-only scheme as portfolio -> `BiddingStrategyError.BIDDING_STRATEGY_NOT_SUPPORTED`.
- Change strategy = `CampaignOperation.update` setting the new oneof (with update_mask).

### Strategy types (BiddingStrategyType -> scheme, valid contexts)
- `MANUAL_CPC` (`manual_cpc`) - standard. `ManualCpc.enhanced_cpc_enabled` has no effect anymore (eCPC deprecated for Search/Display).
- `MANUAL_CPM` - standard, Display-network-only campaigns.
- `MANUAL_CPV` - standard. `MANUAL_CPA` - standard, Local Services only. `FIXED_CPM` - standard. `PERCENT_CPC` - standard.
- `MAXIMIZE_CONVERSIONS` (`maximize_conversions`, optional `target_cpa_micros`) - standard (Search, Display, Video, Demand Gen, PMax, App) and portfolio (Search, Shopping, [PMax per table; PMax guide says no portfolio]).
- `MAXIMIZE_CONVERSION_VALUE` (`maximize_conversion_value`, optional `target_roas` as ratio: 3.5 = 350%) - standard and portfolio.
- `TARGET_CPA` (`target_cpa`) - PORTFOLIO only. For standard tCPA use `maximize_conversions.target_cpa_micros`.
- `TARGET_ROAS` (`target_roas`) - PORTFOLIO only. For standard tROAS use `maximize_conversion_value.target_roas`. (The Shopping guide still lists `target_roas` among campaign bid strategies.)
- `TARGET_SPEND` (`target_spend` = Maximize clicks, optional `cpc_bid_ceiling_micros`; `target_spend_micros` is deprecated) - standard and portfolio.
- `TARGET_IMPRESSION_SHARE` - standard and portfolio (replaces PAGE_ONE_PROMOTED / TARGET_OUTRANK_SHARE).
- `TARGET_CPC` - standard, Demand Gen only, via `Campaign.target_cpc`.
- `TARGET_CPM`, `TARGET_CPV` - standard (video; read-only campaigns).
- Gone: `COMMISSION` (hotel), `PAGE_ONE_PROMOTED`, `TARGET_OUTRANK_SHARE`; `ENHANCED_CPC` deprecated.

### Support by campaign type (as stated in guides)
- Search: manual CPC, Max clicks, Max conv (+tCPA), Max conv value (+tROAS), Target impression share; portfolio tCPA/tROAS too.
- PMax: only Max conv / Max conv value, standard only.
- Demand Gen: Max clicks, tCPA, Max conv, tROAS, Target CPC.
- Standard Shopping: see section 1. Comparison Listing: manual CPC only.
- App: tCPA / tROAS / Max conv / Max conv value per goal type, standard only.
- Display: Manual CPM/CPC, Max conv etc. (no dedicated list in guides).

### Ad group target overrides
- `AdGroup.target_cpa_micros` overrides tCPA from `TargetCpa` (standard or portfolio) or `MaximizeConversions` with a target.
- `AdGroup.target_roas` overrides `TargetRoas` or `MaximizeConversionValue` with target; supported for standard strategies and SEARCH portfolio strategies only (other portfolios -> error).
- `AdGroup.target_cpc_micros` - Demand Gen `TargetCpc`. `AdGroup.target_cpv_micros` - sets CPV for Video `TargetCpv`.
- The strategy itself is campaign-level only; setting a target of another type on the ad group has no effect. Only target_roas / target_cpa can be overridden, not other scheme fields.
- Remove override: update with the field unset and its path in update_mask. Effective values: `effective_target_cpa_micros`/`_source`, `effective_target_roas`/`_source`, `effective_target_cpc`/`_source`.
- Keyword-level manual bids are silently ignored under strategies that don't use them (they take effect if the campaign switches back to manual).

### Bids
- Bids at campaign/ad group/criterion; lower level overrides higher. Multiple bid fields may be set (`cpc_bid_micros`, `cpm_bid_micros`...); only the one relevant to the strategy is used.
- Remove a criterion bid override: update with field unset/null + path in update_mask.
- Display: `display_custom_bid_dimension` picks which dimension holds absolute bids; Search always uses keyword bids.

### Bid modifiers
- `bid_modifier` is a multiplier: 1.2 = +20 %, 0.8 = -20 %, 0.0 = -100 % opt-out (where supported, e.g. device). Multiple applicable modifiers multiply. Valid ranges: see `CampaignBidModifier`/`AdGroupBidModifier` reference (not stated in guides).
- `CampaignBidModifierService`: only `InteractionTypeInfo` with `CALL` (anything else -> `CriterionError`).
- `AdGroupBidModifierService`: `DeviceInfo` and Hotel criteria (date selection, advance booking window, length of stay, check-in day, check-in date range).
- Campaign device adjustment = campaign `DEVICE` criterion with `bid_modifier` (0.0 to opt out of a device).
- Criterion-level `bid_modifier` directly on `CampaignCriterion`/`AdGroupCriterion` for e.g. location, ad schedule, demographics, audiences in Observation mode.
- Interaction with Smart Bidding (which modifiers are honored, e.g. only device -100 %) is NOT stated in the API guides.
```json
{"ad_group_bid_modifier_operation":{"create":{"ad_group":"customers/1234567890/adGroups/555","device":{"type":"MOBILE"},"bid_modifier":0.0}}}
```

### Seasonality adjustments (`BiddingSeasonalityAdjustment`)
- Required: unique `name`, `scope` (`CAMPAIGN` or `CHANNEL`; `CUSTOMER` is read-only), future `start_date_time`/`end_date_time` (account TZ), `conversion_rate_modifier` 0.1-10.0 (1.0 = none).
- CAMPAIGN scope -> `campaigns` (max 2,000); CHANNEL scope -> `advertising_channel_types` (e.g. `SEARCH`). Optional `devices`.
- Best for 1-7 day events; may be less effective beyond 14 days (samples: keep < 14 days).

### Data exclusions (`BiddingDataExclusion`)
- For conversion tracking outages. Required: unique `name`, `scope` (`CAMPAIGN`/`CHANNEL`), `start_date_time` (must be in the past) and `end_date_time` (past or future). Optional `devices`. `status` read-only.
- Not creatable in manager accounts; CAMPAIGN scope max 2,000 campaigns; max 500 active exclusions per account (`RESOURCE_LIMIT`). Frequent/long exclusions hurt Smart Bidding.

### Misc
- Bid strategy recommendations e.g. `MAXIMIZE_CONVERSIONS_OPT_IN` (with suggested budget), `MAXIMIZE_CONVERSION_VALUE_OPT_IN`.
- Max 1,000 bidding strategies attached to ad groups per campaign.

Zdroj: https://developers.google.com/google-ads/api/docs/campaigns/bidding/overview, https://developers.google.com/google-ads/api/docs/campaigns/bidding/strategy-types, https://developers.google.com/google-ads/api/docs/campaigns/bidding/assign-strategies, https://developers.google.com/google-ads/api/docs/campaigns/bidding/override-strategies, https://developers.google.com/google-ads/api/docs/campaigns/bidding/set-bids, https://developers.google.com/google-ads/api/docs/campaigns/bidding/manage-bid-modifiers, https://developers.google.com/google-ads/api/docs/targeting/bid-modifiers, https://developers.google.com/google-ads/api/docs/campaigns/bidding/seasonality-adjustments, https://developers.google.com/google-ads/api/docs/campaigns/bidding/data-exclusions, https://developers.google.com/google-ads/api/docs/shopping-ads/create-campaign, https://developers.google.com/google-ads/api/docs/best-practices/system-limits

---

## 4. Ad groups, keywords, ads

### Ad groups
- Required: `name` (unique within campaign, max 256 chars, `AdGroupError.INVALID_ADGROUP_NAME`), `campaign`. `status` defaults to `ENABLED`. `type` defaults to the campaign's standard type (`SEARCH_STANDARD` for Search, `SHOPPING_PRODUCT_ADS` for Shopping; do not set a type for Demand Gen and App).
- Optional: `cpc_bid_micros` default keyword bid, target overrides, `vertical_ads_format_setting`, `demand_gen_ad_group_settings`, `ai_max_ad_group_setting.disable_search_term_matching`, `audience_setting.use_audience_grouped` (create-time only, immutable), `targeting_setting`.

### Keywords
- `AdGroupCriterion.keyword` = `KeywordInfo{text, match_type}`; match types `EXACT`, `PHRASE`, `BROAD` (guide recommends BROAD with Smart Bidding). Max keyword length 80 chars (`CriterionError.KEYWORD_TEXT_TOO_LONG`).
- Campaign-level keywords can only be negative. Per-ad-group keyword count limits are not in the API guides (Help Center account limits).
- `Campaign.keyword_match_type` is deprecated; setting it to `BROAD` -> `CampaignError.CANNOT_SET_CAMPAIGN_KEYWORD_MATCH_TYPE`. Under AI Max all keywords behave as broad unless search term matching is disabled on the ad group.
- Keyword policy violations: create fails with `PolicyViolationError`; `PolicyViolationDetails.key` (`PolicyViolationKey{policy_name, violating_text}`), `is_exemptible`. If ALL violations are exemptible, resend the same `AdGroupCriterionOperation` with `exempt_policy_violation_keys`; otherwise the text must be changed.

### Responsive search ads (RSA)
- 3-15 unique headlines (<= 30 chars), 2-4 unique descriptions (<= 90 chars); duplicate text -> `AssetError.DUPLICATE_ASSET`; too long -> `AdError.LINE_TOO_WIDE`. >= 1 `final_urls` (ad final URL max 2,084 bytes incl. protocol). `path1`/`path2` <= 15 chars; `path2` requires `path1` (`AdError.CANNOT_SET_PATH2_WITHOUT_PATH1`).
- Serving shows up to 3 headlines + 2 descriptions.
- Pinning: `AdTextAsset.pinned_field` = `HEADLINE_1..3`, `DESCRIPTION_1..2` (other values -> `INVALID_PINNED_FIELD`). Several assets pinned to one slot rotate. Every slot must be fillable by a pinned or distinct unpinned asset; e.g. all 3 headlines pinned to HEADLINE_1 -> `NOT_ENOUGH_AVAILABLE_ASSET_LINKS_FOR_VALID_COMBINATION` (the `..._WITH_FALLBACK_...` variant when customizers lack defaults).
- Ad strength for RSA (`ad_group_ad.ad_strength`, action items) is not documented in the RSA guides (see field reference); PMax asset-group ad strength is in `asset_group.asset_coverage`.
- Auto-created assets (text customization) do not appear in `ad.responsive_search_ad` and can't be removed with `AdService.MutateAds`; use `AdGroupAdService.RemoveAutomaticallyCreatedAssets` (ad level) or `AutomaticallyCreatedAssetRemovalService.RemoveCampaignAutomaticallyCreatedAsset` (campaign-level URL-expansion assets).

### Updating ads
- Content changes: `AdService.MutateAds` (`AdOperation.update` + update_mask) - keeps performance history. Status/remove: `AdGroupAdService.MutateAdGroupAds` (`status` PAUSED/ENABLED with update_mask `status`).
- Updating `headlines`/`descriptions` REPLACES the whole repeated list: send every asset you want to keep (with pins) plus new ones.
- Mutable ad types (AdService): AppAd, AppEngagementAd, AppPreRegistrationAd, DemandGenCarouselAd, DemandGenMultiAssetAd, DemandGenProductAd, DemandGenVideoResponsiveAd, DisplayUploadAd, ResponsiveDisplayAd, ResponsiveSearchAd, ShoppingComparisonListingAd, SmartCampaignAd, VideoResponsiveAd, LocalAd (deprecated).
- NOT mutable (remove + create new, old stats stay but stop updating): ExpandedDynamicSearchAd, ExpandedTextAd (pause/remove only), HotelAd, ImageAd, LegacyAppInstallAd, LegacyResponsiveDisplayAd, ShoppingProductAd, ShoppingSmartAd, TextAd, TravelAd, VideoAd.
- Shareable ads (same ad ID reused in another ad group ad): e.g. RSA, ResponsiveDisplayAd, AppAd, ShoppingProductAd, ImageAd, DisplayUploadAd; not Demand Gen ad types.
```json
{"ad_operation":{"update":{"resource_name":"customers/1234567890/ads/987","final_urls":["https://www.example.com/new"],"responsive_search_ad":{"headlines":[{"text":"Acme Shoes","pinned_field":"HEADLINE_1"},{"text":"Free Returns"},{"text":"New Season Sale"}],"descriptions":[{"text":"Comfortable shoes for every day."},{"text":"Order online, delivered fast."}]}},"update_mask":"final_urls,responsive_search_ad.headlines,responsive_search_ad.descriptions"}}
```

### Ad customizers (RSA)
- Create `CustomizerAttribute` (name unique, case-insensitive; type `TEXT`, `NUMBER`, `PRICE`, `PERCENT`; max 40 enabled attributes per account) and link a value at one level: `CustomerCustomizer`, `CampaignCustomizer`, `AdGroupCustomizer`, `AdGroupCriterionCustomizer` (keywords only). Most specific level wins.
- Syntax in headline/description text: `{CUSTOMIZER.AttributeName:Default}` (attribute name, not ID). PRICE value with currency adjacent, no space (`$100`, `100USD`).
- Built-ins: `{KeyWord:Default}`, `{LOCATION(City):Default}`, `{COUNTDOWN(yyyy-MM-dd HH:mm:ss,daysBefore)}` (account TZ), `{GLOBAL_COUNTDOWN(...)}` (user TZ).
- Length limits (30/90) apply including defaults; if the inserted value doesn't fit, the default is used. Customizers are not allowed in final URLs; the RSA creation guide allows customizers other than countdown in `path1`/`path2`.

### Policy review
- Ad policy violations at create/update raise `PolicyFindingError` with `policy_finding_details`; exemption: resend the same operation with the reported policy topics in the policy validation parameter (`ignorable_policy_topics`). Only `PolicyFindingError`s can be exempted this way.
- Approval/review statuses are read from `ad_group_ad.policy_summary` (approval_status, review_status, policy_topic_entries) - values are not explained in the guides fetched; consult the field reference.

### URLs and tracking
- `final_urls` (no off-domain redirects; lower level overrides higher: keyword > ad > ...), `final_mobile_urls`, `tracking_url_template` (use `{lpurl}`), `final_url_suffix` (with parallel tracking, landing-page params must be in final URL or suffix, not in the template), `url_custom_parameters` (up to 8 per entity, key <= 16 bytes alphanumeric, value <= 200 bytes, referenced as `{_name}`). Lower-level entities override higher (customer < campaign < ad group < ad/keyword). Up to 4 levels of tag nesting.
- Keyword/criterion final URL max 2,047 bytes; ad final URL max 2,084 bytes.
- For mutable ad types, change URLs via `AdService.MutateAds`; for immutable types, remove + recreate (or override at keyword/ad group/campaign level via tracking fields).

### AI Max for Search (setting on Search campaigns)
- Enable: `Campaign.ai_max_setting.enable_ai_max = true` (alone = search term matching only). Text customization (`TEXT_ASSET_AUTOMATION`) and `FINAL_URL_EXPANSION_TEXT_ASSET_AUTOMATION` default `OPTED_OUT`; opting in requires AI Max (`CampaignError.AI_MAX_MUST_BE_ENABLED`); URL expansion requires text customization (`ContextError.OPERATION_NOT_PERMITTED_FOR_CONTEXT`). Disable: `enable_ai_max=false` and opt both out in the same request. Read-only `bundling_required`.
- Text guidelines: <= 25 term exclusions (<= 30 chars), <= 40 messaging restrictions (1-300 chars), type `RESTRICTION_BASED_EXCLUSION` only.
- Location of interest: positive ad group `location` criterion (AI Max only). Brand inclusions: `brand_list` positive (campaign or ad group); exclusions: campaign `brand_list` negative.
- Page feed URL inclusion in standard ad groups: link `PAGE_FEED` asset set via `CampaignAssetSet`, positive `WEBPAGE` criteria only (operands `URL`, `CUSTOM_LABEL`; <= 3 AND conditions; URL `EQUALS` must be the only condition and absolute http(s)).

Zdroj: https://developers.google.com/google-ads/api/docs/campaigns/create-ad-groups, https://developers.google.com/google-ads/api/docs/campaigns/search-campaigns/getting-started, https://developers.google.com/google-ads/api/docs/responsive-search-ads/overview, https://developers.google.com/google-ads/api/docs/responsive-search-ads/create-responsive-search-ads, https://developers.google.com/google-ads/api/docs/ads/mutate-ads, https://developers.google.com/google-ads/api/docs/ads/ad-types, https://developers.google.com/google-ads/api/docs/ads/customize-responsive-search-ads, https://developers.google.com/google-ads/api/docs/policy-exemption/overview, https://developers.google.com/google-ads/api/docs/policy-exemption/keywords, https://developers.google.com/google-ads/api/docs/ads/upgraded-urls/fields, https://developers.google.com/google-ads/api/docs/campaigns/ai-max-for-search-campaigns/getting-started, https://developers.google.com/google-ads/api/docs/best-practices/system-limits

---

## 5. Targeting and criteria

### Levels (criteria table summary)
| Criterion | + | - | Levels / notes |
|---|---|---|---|
| Ad schedule | Y | N | campaign only |
| Age range, Gender, Income range, Extended demographic, Life event, Topic | Y | Y | campaign, ad group (PMax: campaign gender exclusions; age range supported) |
| Parental status | Y | Y | campaign = negative only |
| Audience (`AudienceInfo`) | Y | N | ad group only (Demand Gen/App), needs `use_audience_grouped` |
| User list | Y | Y | campaign, ad group |
| Custom audience / Custom affinity / Combined audience | Y | N | campaign, ad group (custom intent: ad group only) |
| User interest | Y | Y | campaign, ad group; availability depends on campaign type |
| Brand list | Y | Y | campaign; ad group positive only |
| Keyword | Y | Y | ad group; campaign = negative only |
| Language | Y | N | campaign, ad group |
| Location | Y | Y | campaign, ad group (supported types) |
| Proximity, Location group | Y | N | campaign only |
| Device, Carrier, OS version, Mobile device | Y | N | campaign only |
| Placement, YouTube channel/video, Mobile app (category) | Y | Y | campaign, ad group; negative also customer level |
| IP block | N | Y | campaign, customer (max 500 per campaign) |
| Content label | N | Y | campaign, customer (content exclusions) |
| Negative keyword list | N | Y | customer only (one `ACCOUNT_LEVEL_NEGATIVE_KEYWORDS` set per account) |
| Placement list | N | Y | customer (`NEGATIVE_PLACEMENTS` set) |
| Webpage | Y | Y | campaign, ad group; negative = URL exclusion |
| Webpage list | N | Y | campaign (`WEBPAGES` set, allowlist only) |
| Listing group / listing scope | Y | N | ad group / campaign |
- Demographic validation (v24+): excluding every value of a dimension -> `CriterionError.CANNOT_EXCLUDE_ALL_TARGETS`; targeting only `UNDETERMINED` -> `CANNOT_TARGET_ONLY_UNDETERMINED`.

### Location
- Targets are `geoTargetConstants/{criterion_id}`; look up by name with `GeoTargetConstantService.SuggestGeoTargetConstants`. Check `GeoTargetConstant.status` (`ENABLED` / `REMOVAL_PLANNED`).
- Location criteria are IMMUTABLE: to change, query existing `LOCATION`/`PROXIMITY` criteria, then send `remove` for obsolete and `create` for new in ONE `MutateCampaignCriteria` call (atomic swap).
- Exclusion: `negative=true` on `LocationInfo` only; `ProximityInfo` cannot be negative. Proximity radius max 800 km / 500 mi (`INVALID_PROXIMITY_RADIUS`).
- `LocationGroupInfo`: either `enable_customer_level_location_asset_set=true` or `location_group_asset_sets` (not both, not combined with `geo_target_constants`); radius requires `radius` + `radius_units` (`MILLI_MILES`/`METERS` with asset sets; `MILES`/`METERS` with a single geo constant filter).
- Presence vs interest: `Campaign.geo_target_type_setting.positive_geo_target_type` = `PRESENCE_OR_INTEREST` (default, broadest) or `PRESENCE`; `negative_geo_target_type` = `PRESENCE` (recommended default).
- Requires the EU political declaration on the campaign (section 1).
```json
{"campaign_criterion_operation":{"create":{"campaign":"customers/1234567890/campaigns/111","proximity":{"geo_point":{"latitude_in_micro_degrees":50087000,"longitude_in_micro_degrees":14421000},"radius":10,"radius_units":"KILOMETERS"}}}}
```

### Language
- `LanguageInfo.language_constant` (`languageConstants/1000` = English), positive only; disallowed language -> `CriterionError.CANNOT_TARGET_LANGUAGE` (v24+). PMax validates against the campaign country; PMax retail may also use the Merchant Center feed language.

### Ad schedule
- Campaign-level, positive only (`AdScheduleInfo`: day_of_week, start_hour, start_minute, end_hour, end_minute; minutes use the `MinuteOfHour` enum ZERO/FIFTEEN/THIRTY/FORTY_FIVE per proto). Bid adjustment via `CampaignCriterion.bid_modifier`. Max schedules per day and other limits are NOT stated in the API guides.

### Device
- Campaign `DEVICE` criterion (positive only), opt out with `bid_modifier = 0.0`; ad group device adjustments via `AdGroupBidModifier`.

### Audiences
- Two systems: `UserList` (audience segments) for Display, Search, Video, Hotel, Standard Shopping - targeted with `CampaignCriterion.user_list` / `AdGroupCriterion.user_list`; `Audience` (composite of segments + age/gender/income/parental + exclusions) for PMax (signal), Demand Gen and App (`AdGroupCriterion.audience`).
- `Audience`: unique name; one dimension per type (`TOO_MANY_DIMENSIONS_OF_SAME_TYPE`); `exclusion_dimension` accepts only user list segments (`DIMENSION_INVALID`); duplicates -> `DUPLICATE_AUDIENCE_SEGMENT`; segment count limit exists (`TOO_MANY_SEGMENTS`) but number not given.
- `use_audience_grouped=true` on ad group (create-only, immutable) is required for `AudienceInfo`; on campaign (optional) it blocks campaign-level segment/demographic exclusions.
- UserList types: CRM/Customer Match, rule-based, logical (combinations), basic, lookalike (Demand Gen only), similar (legacy, sunset). `membership_life_span` (ignored for logical/rule-based), `membership_status`. Only the owning account can modify a list; test accounts can't use user lists. GA audiences appear as REMARKETING/RULE_BASED lists (identify by name).
- Customer Match: since 2026-04-01 `OfflineUserDataJobService`/`UserDataService` uploads fail with `CUSTOMER_NOT_ALLOWLISTED_FOR_THIS_FEATURE` for projects without Customer Match activity 2025-10-01..2026-03-31 -> use the Data Manager API.
- Custom segments: `CustomAudience` (`CustomAudienceService`, keywords/URLs/apps; replaces custom intent/affinity) for Display, Demand Gen, Video, PMax; target via `custom_audience` on campaign or ad group criteria.
- Combined audiences: `CombinedAudienceInfo`, positive only, campaign or ad group.
- Targeting vs Observation: `targeting_setting.target_restrictions[]` per `TargetingDimension` (`AUDIENCE`, `TOPIC`, `GENDER`, `AGE_RANGE`, `PLACEMENT`, `PARENTAL_STATUS`, `INCOME_RANGE`): `bid_only=false` = Targeting (restricts reach, API default when a dimension is omitted), `bid_only=true` = Observation. UI may default to Observation for audiences on Search; API does not -> for audiences on Search/Shopping explicitly set `AUDIENCE` `bid_only=true`.
- `targeting_setting` can exist on campaign OR ad group, not both: remove it from one level (update with empty `target_restrictions` + mask) before setting the other.
```json
{"ad_group_operation":{"update":{"resource_name":"customers/1234567890/adGroups/555","targeting_setting":{"target_restrictions":[{"targeting_dimension":"AUDIENCE","bid_only":true}]}},"update_mask":"targeting_setting.target_restrictions"}}
```

### Placements and content exclusions
- `PlacementInfo.url` max 250 chars (protocol stripped, `PLACEMENT_URL_IS_TOO_LONG`), max depth 2, `adsenseformobileapps.com` not allowed. Positive at campaign/ad group; negative at campaign, ad group, customer.
- Account-wide placement exclusion: `CustomerNegativeCriterion.placement` or `.placement_list` (NEGATIVE_PLACEMENTS shared set). Campaign: `CampaignSharedSet` with a NEGATIVE_PLACEMENTS set.
- Content exclusions: negative `ContentLabelInfo` at campaign or customer level. YouTube channel/video and mobile app exclusions also at customer level.

### Negative keyword lists and account-level negatives
- Shared set flow: `SharedSet{name, type}` -> `SharedCriterion{shared_set, keyword{text, match_type}}` (batch them in one `MutateSharedCriteria`) -> attach.
- `NEGATIVE_KEYWORDS` (supported on Search, Display, Shopping, MULTI_CHANNEL App, LOCAL) and `NEGATIVE_PLACEMENTS` attach to campaigns ONLY via `CampaignSharedSet`; they apply to all ad groups in the campaign.
- `ACCOUNT_LEVEL_NEGATIVE_KEYWORDS`: attach via `CustomerNegativeCriterion.negative_keyword_list.shared_set`; max one per account. A manager account can own the set and attach it to a client (create the `CustomerNegativeCriterion` in the client account referencing the manager's shared set).
- PMax: campaign-level negative `KEYWORD` criteria (max 10,000); search themes respect PMax brand exclusions and account-level negative keywords (Google Ads Developer Blog, Nov 2023; not restated in the guides).
```json
[
 {"shared_set_operation":{"create":{"resource_name":"customers/1234567890/sharedSets/-1","name":"Neg - jobs","type":"NEGATIVE_KEYWORDS"}}},
 {"shared_criterion_operation":{"create":{"shared_set":"customers/1234567890/sharedSets/-1","keyword":{"text":"jobs","match_type":"PHRASE"}}}},
 {"campaign_shared_set_operation":{"create":{"campaign":"customers/1234567890/campaigns/111","shared_set":"customers/1234567890/sharedSets/-1"}}},
 {"customer_negative_criterion_operation":{"create":{"negative_keyword_list":{"shared_set":"customers/1234567890/sharedSets/222"}}}}
]
```
(the last op assumes 222 is an `ACCOUNT_LEVEL_NEGATIVE_KEYWORDS` set.)

### Brand lists / brand exclusions
- `BRANDS` shared set containing `BrandInfo` shared criteria. Brand entity IDs can be looked up with `BrandSuggestionService.SuggestBrands` (details not in guides).
- Attach with `CampaignCriterion.brand_list.shared_set`: positive = brand restriction/inclusion (Search, AI Max), negative = brand exclusion. Ad group `brand_list` positive only. PMax: brand exclusion only (negative). Shopping: `shopping_setting.ignore_brand_exclusion_in_shopping_ads` (v24.2+) lets Shopping ads ignore brand exclusions.
- Other shared set types: `WEBPAGES` (allowlist; campaign `webpage_list`), `VERTICAL_ADS_ITEM_GROUP_RULE_LIST` (ad group), `RETAIL_FILTER` (v24+, allowlist; ad group `retail_filter_bundle` or PMax listing group filter dimension).

Zdroj: https://developers.google.com/google-ads/api/docs/targeting/overview, https://developers.google.com/google-ads/api/docs/targeting/criteria, https://developers.google.com/google-ads/api/docs/targeting/location-targeting, https://developers.google.com/google-ads/api/docs/targeting/bid-modifiers, https://developers.google.com/google-ads/api/docs/targeting/targeting-settings, https://developers.google.com/google-ads/api/docs/targeting/shared-sets, https://developers.google.com/google-ads/api/docs/remarketing/overview, https://developers.google.com/google-ads/api/docs/remarketing/audiences, https://developers.google.com/google-ads/api/docs/remarketing/audience-segments/getting-started, https://developers.google.com/google-ads/api/docs/remarketing/audience-segments/custom-audiences, https://developers.google.com/google-ads/api/docs/demand-gen/audience-targeting, https://developers.google.com/google-ads/api/performance-max/create-campaign-criteria, https://developers.google.com/google-ads/api/docs/campaigns/ai-max-for-search-campaigns/getting-started, https://developers.google.com/google-ads/api/docs/api-policy/eu-par, https://developers.google.com/google-ads/api/docs/best-practices/system-limits

# Google Ads API v25 – Assets, Conversions, Audiences, Planning, Experiments & Account Tools

Scope: rules, workflows and gotchas from the official guides (developers.google.com/google-ads/api/docs, pages last updated Sep–Oct 2026). Field lists are intentionally omitted – use the proto reference. "Not stated in docs" means the guide pages don't cover it; don't assume.

---

## 1. Assets

### Object model
- `Asset` = shareable unit of content. `AssetType` = what it contains (TEXT, IMAGE, SITELINK...). `AssetFieldType` = how it is used in a given link (HEADLINE, DESCRIPTION, MARKETING_IMAGE, SITELINK, ...). The same asset can be linked with different field types.
- Link resources: `CustomerAsset`, `CampaignAsset`, `AdGroupAsset`, `AssetGroupAsset` (PMax), `AssetSetAsset`. Asset-set links: `CustomerAssetSet`, `CampaignAssetSet`, `AdGroupAssetSet`.
- A campaign can have many `CampaignAssetSet`s; each `CampaignAssetSet` links exactly one campaign. Create the `Campaign` and the `AssetSet` (with assets) first.
- Link resource names: `customers/{cid}/campaignAssets/{campaign_id}~{asset_id}~{field_type}` (ad group links analogous). On `CampaignAsset`, `asset`, `campaign` and `field_type` are **immutable** → to change the field type or target, remove the link and create a new one. Only `status` (AssetLinkStatus) is mutable.
- Serving state: link resources expose output-only `primary_status`, `primary_status_reasons[]`, `primary_status_details[]` (policy/quality approvals folded in) vs. advertiser-set `status` (ENABLED/PAUSED/REMOVED). `source` (AssetSource) = ADVERTISER vs AUTOMATICALLY_CREATED.

### Creating assets – rules
- Every asset type except `TextAsset` must be created first with `AssetService.MutateAssets`, then referenced by resource name. Text for ads (RSA headlines, RDA texts) is created **inline** in the ad as `AdTextAsset{text}`.
- `AssetService` supports create **and update** for mutable types (sitelink, callout, promotion, price, call, structured snippet, lead form, mobile app, hotel callout, business message). `TextAsset`/`ImageAsset` (and YouTube video) are immutable once uploaded; you can't edit or delete the asset itself – you manage links (remove/pause the link).
- Image & media bundle assets need a name; if an existing name is supplied, a unique suffix is appended. If an image with **identical content** already exists, the new name is silently dropped (dedup by content) – the existing asset is effectively returned.
- Image asset create (snake_case JSON):
  ```json
  {"operations":[{"create":{"name":"Hero 1200x628","type":"IMAGE",
    "image_asset":{"data":"<base64 bytes>"}}}]}
  ```
  (`file_size`, `mime_type`, `full_size{width_pixels,height_pixels,url}` may be set; samples set them.)
- Sitelink etc. on account / campaign / ad group: create asset, then link:
  ```json
  {"operations":[{"create":{"campaign":"customers/1/campaigns/2",
    "asset":"customers/1/assets/3","field_type":"SITELINK"}}]}
  ```

### Which asset goes where
- Linked via Customer/Campaign/AdGroupAsset (all mutable): SITELINK, CALLOUT, STRUCTURED_SNIPPET, CALL, PRICE, PROMOTION, MOBILE_APP, HOTEL_CALLOUT, BUSINESS_MESSAGE.
- LEAD_FORM: **CampaignAsset only**.
- AD_IMAGE (image extension): AdGroupAsset / CampaignAsset (immutable asset).
- BUSINESS_NAME (text) and BUSINESS_LOGO: CampaignAsset / CustomerAsset.
- Directly in ads: YOUTUBE_VIDEO (App, App engagement, Local, RDA); MEDIA_BUNDLE/CUSTOM_LAYOUT (App, Display upload); image fields MARKETING_IMAGE, SQUARE_MARKETING_IMAGE, PORTRAIT_MARKETING_IMAGE, LOGO, LANDSCAPE_LOGO, CLASSIC_DISPLAY_IMAGE (App, App engagement, Local, RDA, Demand Gen multi-asset); text HEADLINE, LONG_HEADLINE, DESCRIPTION, MANDATORY_AD_TEXT, CALL_TO_ACTION_SELECTION, BUSINESS_NAME; CALL_TO_ACTION (Local, RDA).
- Demand Gen also takes `DemandGenCarouselCardAsset`; PMax creative assets go through `AssetGroupAsset`.
- **PMax brand assets**: if brand guidelines are enabled, BUSINESS_NAME, LOGO and LANDSCAPE_LOGO are linked with `CampaignAsset` (not `AssetGroupAsset`); if disabled, via `AssetGroupAsset`. Sitelinks/callouts etc. for PMax go on `CampaignAsset`, never on the asset group.
- Location assets are not created directly (see below). Affiliate locations likewise via asset sets.

### Asset sets
- Types linked by `CampaignAssetSet`: PAGE_FEED, DYNAMIC_EDUCATION, DYNAMIC_CUSTOM, DYNAMIC_HOTELS_AND_RENTALS, DYNAMIC_REAL_ESTATE, DYNAMIC_LOCAL, DYNAMIC_FLIGHTS, DYNAMIC_JOBS, DYNAMIC_TRAVEL (assets added with `AssetSetAssetService`).
- LOCATION_SYNC (system-generated location assets): Customer/Campaign/AdGroupAssetSet. Location groups BUSINESS_PROFILE_DYNAMIC_LOCATION_GROUP, CHAIN_DYNAMIC_LOCATION_GROUP, STATIC_LOCATION_GROUP: Campaign/AdGroupAssetSet.
- `AssetSet` ≠ `SharedSet` (negative lists) – different services.
- PMax page feed + text customization: the page-feed `CampaignAssetSet` and `TEXT_ASSET_AUTOMATION = OPTED_IN` must both be present, else `OPERATION_NOT_PERMITTED_FOR_CONTEXT`. Order: to add the CampaignAssetSet, opt in first; to opt out, remove the CampaignAssetSet first.

### Location assets (Business Profile)
- Create `AssetSet{type: LOCATION_SYNC, location_set{location_ownership_type: BUSINESS_OWNER|AFFILIATE, <source>}}` and link with `CustomerAssetSetService.MutateCustomerAssetSets`; Google then generates the location assets. Sources: `business_profile_location_set` (GBP), `chain_location_set` (chain IDs, typically affiliate), `maps_location_set` (manual Place IDs).
- Only **one ENABLED LOCATION_SYNC set per customer**; remove it to switch source type.
- GBP sync needs `http_authorization_token` = OAuth access token of the Google account in `email_address` with scope `https://www.googleapis.com/auth/business.manage` and read access to the locations.
- Campaigns/ad groups inherit all customer-level locations. For a subset create a location-group AssetSet with `location_group_parent_asset_set_id` = sync set id: dynamic `BUSINESS_PROFILE_DYNAMIC_LOCATION_GROUP` (`business_profile_location_group` filters) or `CHAIN_DYNAMIC_LOCATION_GROUP`; `maps_location_set` cannot have a dynamic group. `STATIC_LOCATION_GROUP` works for any source but you add assets manually (query `asset_set_asset` for generated asset names, then `AssetSetAssetService`); it does not auto-update. Link via `CampaignAssetSetService` / `AdGroupAssetSetService`.
- `listing_id_filters[]` is signed int64 but GBP listing IDs are uint64 → IDs ≥ 2^63 must be converted (two's complement).

### Automatically created assets & automation settings
- Account-level opt-in/out of "automated assets" (auto sitelinks, callouts, etc.) is **UI-only**. API can only pause/remove their links and read stats. You cannot create/update automated assets or create links for them.
- Pause link = temporary (Google won't re-enable it). Remove link = permanent. Google caps automated assets per type per entity (e.g. auto sitelinks per campaign): **paused links count against that cap, removed links don't**. Automated assets don't count toward manual-asset limits.
- Find them: `SELECT asset.id, asset.name FROM asset WHERE asset.source = 'AUTOMATICALLY_CREATED'`; for ad-linked assets `ad_group_ad_asset_view.source = 'AUTOMATICALLY_CREATED'`. `Asset.source` is only accurate for mutable assets; for RSA use `ad_group_ad_asset_view.source`.
- Text customization (formerly "automatically created assets") assets cannot be modified; mutable types like sitelinks can't be linked to them.
- Removal services:
  - `AutomaticallyCreatedAssetRemovalService.RemoveCampaignAutomaticallyCreatedAsset` – removes text-customization assets from a **campaign**. Operation fields (all required): `asset`, `campaign`, `field_type`. Errors: `AutomaticallyCreatedAssetRemovalError`.
    ```json
    {"operations":[{"asset":"customers/1/assets/9","campaign":"customers/1/campaigns/2","field_type":"HEADLINE"}],"partial_failure":true}
    ```
  - `AdGroupAdService.RemoveAutomaticallyCreatedAssets{ad_group_ad, assets_with_field_type[{asset, asset_field_type}]}` – removes them from a single ad (e.g. RSA).
- Campaign-level automation: `Campaign.asset_automation_settings[] {asset_automation_type, asset_automation_status: OPTED_IN|OPTED_OUT}`:
  - `TEXT_ASSET_AUTOMATION` (text customization) – PMax default ON, Search default OFF.
  - `FINAL_URL_EXPANSION_TEXT_ASSET_AUTOMATION` – PMax ON, Search OFF; if final URL expansion is active, dynamic text generation for expanded landing pages **cannot be opted out**.
  - `GENERATE_ENHANCED_YOUTUBE_VIDEOS` (PMax, ON; OPTED_OUT keeps your videos unedited), `GENERATE_IMAGE_ENHANCEMENT` (PMax, ON), `GENERATE_IMAGE_EXTRACTION` (PMax; default = account-level Dynamic Image Extension setting, which is UI-only).
  - `AUTOMATED_VIDEO_CRAWL` (PMax, v25+, default OFF): opt in + `automated_video_crawl_setting.automated_video_crawl_infos[{url, source_platform: LANDING_PAGE|SOCIAL|YOUTUBE, enabled}]`.
  - PMax with no video in the asset group may get auto-generated videos; uploading your own video stops that.
- Ad-level (ad group ad, Demand Gen) automation types, default ON unless noted: DemandGenMultiAssetAd – GENERATE_ANIMATED_IMAGES_FROM_OTHER_ASSETS, GENERATE_DESIGN_VERSIONS_FOR_IMAGES, GENERATE_VIDEOS_FROM_OTHER_ASSETS; DemandGenVideoResponsiveAd – GENERATE_LANDING_PAGE_TEXT, GENERATE_SHORTER_YOUTUBE_VIDEOS, GENERATE_VERTICAL_YOUTUBE_VIDEOS, GENERATE_LANDING_PAGE_PREVIEW (OFF).
- `Campaign.text_guidelines` (v23+, PMax & AI Max): term exclusions ≤25 items, ≤30 chars each; messaging restrictions ≤40 items, ≤300 chars each, type only `RESTRICTION_BASED_EXCLUSION`.

### Image / PMax asset requirements
- Formats GIF, JPG, PNG; max 5120 KB per image.
- MARKETING_IMAGE 1.91:1 (rec 1200×628, min 600×314), 1–20; SQUARE_MARKETING_IMAGE 1:1 (1200×1200, min 300×300), 1–20; PORTRAIT_MARKETING_IMAGE 4:5 (960×1200, min 480×600), 0–20; LOGO 1:1 (1200×1200, min 128×128), 1–5; LANDSCAPE_LOGO 4:1 (1200×300, min 512×128), 0–20.
- PMax text: HEADLINE ≤30 chars, 3–15; LONG_HEADLINE ≤90, 1–5; DESCRIPTION ≤90, 2–5; BUSINESS_NAME ≤25, exactly 1 (if brand guidelines off). YOUTUBE_VIDEO 0–15 (16:9, 1:1 or 9:16, ≥10 s); CALL_TO_ACTION_SELECTION ≤1; MEDIA_BUNDLE ≤1 (<150 KB).
- **Aspect ratio is validated when the asset is linked, not on upload** → `ASPECT_RATIO_NOT_ALLOWED` at link time. Recommended dimensions are not requirements; min size + ratio are.
- Retail (Merchant Center-linked) PMax auto-generates minimum assets; requirements still apply when creating non-retail asset groups or updating assets on any asset group.

### YouTube video upload (v23+)
- `YouTubeVideoUploadService.CreateYouTubeVideoUpload` (resumable/multipart; supported in .NET, PHP, Python libs and REST; other libs: upload via YouTube Data API v3, then create `YoutubeVideoAsset` with the video ID).
- `channel_id` set = advertiser brand channel (user OAuth only, **not service accounts**); omitted = Google-managed channel linked to the Ads account. `video_privacy`: PUBLIC only for brand channels; UNLISTED is default and the only option for Google-managed.
- `state`: PENDING → UPLOADED → PROCESSED (usable) | FAILED | REJECTED | UNAVAILABLE. Poll `SELECT you_tube_video_upload.video_id, you_tube_video_upload.state FROM you_tube_video_upload WHERE you_tube_video_upload.resource_name = '...'`; after PROCESSED create `Asset{type: YOUTUBE_VIDEO, youtube_video_asset{youtube_video_id}}`.
- REST resumable: `POST https://googleads.googleapis.com/resumable/upload/v25/customers/{cid}/youTubeVideoUploads:create` with `X-Goog-Upload-Protocol: resumable`, `X-Goog-Upload-Command: start`, `X-Goog-Upload-Header-Content-Length`; read `x-goog-upload-url` + `x-goog-upload-chunk-granularity`; PUT chunks (`X-Goog-Upload-Offset`, `upload`), last chunk `upload, finalize`.
- `UpdateYouTubeVideoUpload` can change only `video_title`, `video_description`, `video_privacy`. `RemoveYouTubeVideoUpload` deletes the video from the asset library **and from YouTube**.

### Performance, approval & reporting
- Metrics per link: `customer_asset`, `campaign_asset`, `ad_group_asset` (select `ad_group.id` for per-ad-group rows). Aggregated by field type (auto + manual): `asset_field_type_view`.
- Ad-level: `ad_group_ad_asset_view` (only App ads, Demand Gen, RSA assets) with `performance_label` BEST/GOOD/LOW/LEARNING (impressions but not significant)/PENDING (no data, may still be in review).
- Serving/approval: link `primary_status` + `primary_status_reasons` (see Object model). The asset guides don't describe policy fields further – check the proto.
- Asset recommendations applicable via `RecommendationService.ApplyRecommendation`: CALLOUT_ASSET, SITELINK_ASSET, CALL_ASSET, LEAD_FORM_ASSET, RESPONSIVE_SEARCH_AD_ASSET; IMPROVE_PERFORMANCE_MAX_AD_STRENGTH points to asset groups needing work.
- Not stated in the asset guides: per-type validation rules for price/promotion/lead form/structured snippet assets (header values, item counts, etc.) – rely on proto field docs and API errors.

Zdroj: https://developers.google.com/google-ads/api/docs/assets/overview · https://developers.google.com/google-ads/api/docs/assets/working-with-assets · https://developers.google.com/google-ads/api/docs/assets/location-assets · https://developers.google.com/google-ads/api/docs/assets/automated-assets · https://developers.google.com/google-ads/api/docs/assets/asset-automation-settings · https://developers.google.com/google-ads/api/docs/assets/upload-videos · https://developers.google.com/google-ads/api/docs/assets/fetching-assets · https://developers.google.com/google-ads/api/performance-max/assets · https://developers.google.com/google-ads/api/performance-max/asset-requirements · https://developers.google.com/google-ads/api/reference/rpc/v25/RemoveCampaignAutomaticallyCreatedAssetOperation · https://developers.google.com/google-ads/api/reference/rpc/v25/RemoveAutomaticallyCreatedAssetsRequest · https://developers.google.com/google-ads/api/reference/rpc/v25/CampaignAsset

---

## 2. Conversions

### Platform status (important)
- **Since June 15, 2026 `ConversionUploadService.UploadClickConversions` is restricted to developer tokens that have previously uploaded offline click conversions.** New integrations are directed to the **Data Manager API** for offline/ECL conversions. Existing integrations keep working.
- Upload request limits: `UploadClickConversions` 2,000 conversions/request; `UploadCallConversions` 2,000; `UploadConversionAdjustments` 2,000 adjustments/request. Always batch.

### Conversion customer (who owns conversions)
- First query: `SELECT customer.conversion_tracking_setting.google_ads_conversion_customer, customer.conversion_tracking_setting.conversion_tracking_status, customer.conversion_tracking_setting.conversion_tracking_id, customer.conversion_tracking_setting.cross_account_conversion_tracking_id, customer.conversion_tracking_setting.accepted_customer_data_terms, customer.conversion_tracking_setting.enhanced_conversions_for_leads_enabled FROM customer`.
- `google_ads_conversion_customer` (populated even if tracking is off) is the `customer_id` to use for creating conversion actions, conversion goals at customer level, custom goals and **all uploads**. With cross-account conversion tracking (CACT) it is the manager.
- `NOT_CONVERSION_TRACKED` → create at least one `ConversionAction` to enable tracking.
- CACT changes via API are allowlist-only (otherwise UI): set `Customer.conversion_tracking_setting.google_ads_conversion_customer` to the manager with `login-customer-id` = manager. Side effects: client adopts manager's default value rules and default lifecycle goals; campaigns targeting specific actions switch to manager defaults; one manager per account. Uploader must be the owner manager or a descendant. Don't upload the same conversion through multiple accounts.

### Conversion action types (what you can create)
- Creatable: `WEBPAGE` (tag; `tag_snippets[]` with `TrackingCodeType` WEBPAGE / WEBPAGE_ONCLICK / CLICK_TO_CALL; `global_site_tag` on every page, `event_snippet` on conversion page), `UPLOAD_CLICKS` (offline clicks / ECL), `UPLOAD_CALLS`, `AD_CALL` (calls from call assets / call-only ads; put the action in `CallAsset.call_conversion_action`; default counted call length 60 s), `WEBSITE_CALL` (needs snippets + Google forwarding number + call asset linked), `CLICK_TO_CALL` (clicks on number on mobile site, no real call), `GOOGLE_PLAY_DOWNLOAD`, `GOOGLE_PLAY_IN_APP_PURCHASE`.
- Enable-only: GA4 (`GOOGLE_ANALYTICS_4_CUSTOM`, `GOOGLE_ANALYTICS_4_PURCHASE`), Firebase (`FIREBASE_ANDROID_*`/`FIREBASE_IOS_*`: APP_AD_IMPRESSION, FIRST_OPEN, IN_APP_PURCHASE, CUSTOM) and `THIRD_PARTY_APP_ANALYTICS_*` – import by changing `status` HIDDEN → ENABLED. GA4 allows changing only `status`, `primary_for_goal`, `category`, `name`, `value_settings`, and remove; anything else (or any change to Universal Analytics actions) → `MUTATE_NOT_ALLOWED`. `app_id` not updatable.
- Not creatable: `STORE_SALES`, `STORE_SALES_DIRECT_UPLOAD` (uploads of transactions supported). Read-only: ANDROID_APP_PRE_REGISTRATION, ANDROID_INSTALLS_ALL_OTHER_APPS, FLOODLIGHT_ACTION, FLOODLIGHT_TRANSACTION, GOOGLE_HOSTED, LEAD_FORM_SUBMIT, SALESFORCE, SEARCH_ADS_360, SMART_CAMPAIGN_AD_CLICKS_TO_CALL, SMART_CAMPAIGN_MAP_CLICKS_TO_CALL, SMART_CAMPAIGN_MAP_DIRECTIONS, SMART_CAMPAIGN_TRACKED_CALLS, STORE_VISITS, WEBPAGE_CODELESS. `UNKNOWN` types appear in reports but can't be managed.
- Category: use `DOWNLOAD` only with `GOOGLE_PLAY_DOWNLOAD`.

### Creating conversion actions – rules
- `ConversionActionService.MutateConversionActions`. Name must be unique (`ConversionActionError.DUPLICATE_NAME`, most common error).
- Defaults: `counting_type` MANY_PER_CLICK; attribution `GOOGLE_SEARCH_ATTRIBUTION_DATA_DRIVEN`; `primary_for_goal` set automatically; enhanced conversions auto-enabled for API-sent data (can be disabled in UI).
- `attribution_model_settings.attribution_model`: only `GOOGLE_ADS_LAST_CLICK` or `GOOGLE_SEARCH_ATTRIBUTION_DATA_DRIVEN` (rule-based → `CANNOT_SET_RULE_BASED_ATTRIBUTION_MODELS`).
- `click_through_lookback_window_days`: 1–60 for AD_CALL/WEBSITE_CALL, 1–90 for others. `view_through_lookback_window_days`: 1–30, must be unset for AD_CALL/WEBSITE_CALL. Changing click lookback only affects clicks after the change.
- AD_CALL/WEBSITE_CALL require `value_settings.always_use_default_value = true` (else `INVALID_VALUE`). `phone_call_duration_seconds` only on call actions (`VALUE_MUST_BE_UNSET` otherwise).
- `type` and `app_id` immutable. `include_in_conversions_metric` is deprecated/immutable (`IMMUTABLE_FIELD`) – use `primary_for_goal`. Any enum set to `UNKNOWN` → `RequestError.INVALID_ENUM_VALUE`.
  ```json
  {"operations":[{"create":{"name":"CRM qualified lead","type":"UPLOAD_CLICKS","category":"QUALIFIED_LEAD",
    "status":"ENABLED","click_through_lookback_window_days":90,
    "value_settings":{"default_value":50,"default_currency_code":"CZK","always_use_default_value":false}}}]}
  ```

### Conversion goals (what bidding optimizes for)
- A goal = unique (`category`, `origin`) among actions in the conversion customer (UI "Conversion source" = origin).
- `CustomerConversionGoal`, `CampaignConversionGoal`, `ConversionGoalCampaignConfig` are system-generated: **update only** (no create/remove). `CustomConversionGoal` is create/remove via `CustomConversionGoalService.MutateCustomConversionGoals`.
- `customer_id`: CustomerConversionGoal & CustomConversionGoal → **conversion customer**; CampaignConversionGoal & ConversionGoalCampaignConfig → the **ads account**.
- `biddable` = "use as account-default goal". New category/origin defaults to `true`, except (default false): origin GOOGLE_HOSTED with BEGIN_CHECKOUT, CONSIDERATION, CONTACT, CONVERTED_LEAD, ENGAGEMENT, GET_DIRECTIONS, PAGE_VIEW, QUALIFIED_LEAD, SIGNUP, PURCHASE; STORE with STORE_SALE, STORE_VISIT; LOCAL_SERVICES_ADS with PHONE_CALL_LEAD, MESSAGE_LEAD, BOOK_APPOINTMENT, CONVERTED_LEAD. A new campaign goal is also false if another goal of the same category on that campaign is false.
- `ConversionAction.primary_for_goal`: true → counted in Conversions + used for bidding if its goal is biddable; false → "secondary", only in All conv. (unless in a custom goal).
- `ConversionGoalCampaignConfig.goal_config_level`: any update to a campaign's `CampaignConversionGoal` or applying a custom goal switches it to `CAMPAIGN` → campaign **stops inheriting** later customer-level goal changes. Set back to `CUSTOMER` to reset campaign goals to account defaults (also drops custom goal).
- Make a campaign optimize toward specific actions: (1) create `CustomConversionGoal{name, conversion_actions[]}` in the conversion customer (actions are used even if `primary_for_goal = false`); (2) update `ConversionGoalCampaignConfig{custom_conversion_goal}` with `update_mask: "custom_conversion_goal"`; (3) set `biddable=false` on the campaign's `CampaignConversionGoal`s you don't want.
  ```json
  {"operations":[{"update":{"resource_name":"customers/1/conversionGoalCampaignConfigs/2",
    "custom_conversion_goal":"customers/1/customConversionGoals/3"},"update_mask":"custom_conversion_goal"}]}
  ```
- GAQL: `customer_conversion_goal` (category, origin, biddable), `campaign_conversion_goal` (campaign, category, origin, biddable), `conversion_goal_campaign_config` (goal_config_level, custom_conversion_goal), `custom_conversion_goal`. The UI "Other" goal = category `DEFAULT`. Filter actions by `status = 'ENABLED'` to match the UI goal summary.
- `Campaign.selective_optimization` is only for App campaigns.

### Customer lifecycle goals
- `GoalService` `Goal{goal_type: NEW_CUSTOMER_ACQUISITION|CUSTOMER_RETENTION|LOYALTY_RETENTION}` (one per type, `*_GOAL_ALREADY_EXISTS`); value via `additional_value` or `value_multiplier` (not for NCA); high-LTV value must exceed the base. Campaign level `CampaignGoalConfigService`: NCA `target_option` TARGET_ALL / TARGET_SPECIFIC (new customers only, no overrides); retention TARGET_SPECIFIC allowlist-only; retention needs PMax + Customer Match list classified by `UserListCustomerType` (create/remove only). Incompatible combos → `CANNOT_USE_INCOMPATIBLE_CLO_GOALS`. With CACT customer-level goals live in the conversion account.

### Consent (EEA / EU user consent)
- `Consent{ad_user_data, ad_personalization}` with ConsentStatus GRANTED/DENIED. **`ad_personalization` can only be set for OfflineUserDataJobService and UserDataService**; conversions use `ad_user_data`.
- Set per payload (`ClickConversion.consent`, `CallConversion.consent`, `UserData.consent`/CM job metadata) or account default in UI (Tools > Data Manager > Consent settings). Strongly recommended – missing/improper consent is a common cause of low or no attribution. If consent is unknown send `DENIED` (never UNKNOWN → INVALID_ENUM_VALUE).

### Offline click conversions & enhanced conversions for leads (ECL)
- Prereqs for ECL: `accepted_customer_data_terms = true` and `enhanced_conversions_for_leads_enabled = true` (set in UI). Recommended to have the Google tag capturing the lead form; without it include `gclid` on each conversion.
- Conversion action must be `UPLOAD_CLICKS` and live in the conversion customer of the clicked account. Wait ≥6 h after creating the action (`TOO_RECENT_CONVERSION_ACTION`).
- Request: `customer_id` = conversion customer; `partial_failure = true` (mandatory); `job_id` optional – unset → system assigns from [2^31, 2^63); set the same value in [0, 2^31) on all requests of one logical job to get one `job_summaries` row in diagnostics.
- `ClickConversion` essentials: one of `gclid` / `gbraid` (web ad → iOS app) / `wbraid` (iOS app ad → web) (never gclid together with a braid; not both braids – `GBRAID_WBRAID_BOTH_SET`/`VALUE_MUST_BE_UNSET`); `conversion_action`; `conversion_date_time` `"yyyy-mm-dd HH:mm:ss+|-HH:mm"` (e.g. `"2026-10-01 14:05:00+02:00"`, any timezone; use account tz to match UI); `conversion_value`, `currency_code`; `order_id` (strongly recommended; if set at upload it **must** be used for later adjustments); `consent`; `user_identifiers` (ECL, up to 5, one identifier per `UserIdentifier`); `cart_data{merchant_id, feed_country_code, feed_language_code, local_transaction_cost, items[{product_id, quantity, unit_price}]}`; `conversion_environment` APP/WEB; `session_attributes_encoded` or `session_attributes_key_value_pairs`; `user_ip_address` (end-user device IP, not your server).
- Setting `user_identifiers` makes the upload ECL. ECL must **not** use `external_attribution_data`/externally attributed actions and must **not** include `custom_variables` (conversions with user data + custom variables are dropped). Custom variables are also unsupported with gbraid/wbraid.
  ```json
  {"customer_id":"1234567890","partial_failure":true,"job_id":42,
   "conversions":[{"conversion_action":"customers/1234567890/conversionActions/555",
     "gclid":"Cj0KCQ...","conversion_date_time":"2026-10-01 14:05:00+02:00",
     "conversion_value":1200,"currency_code":"CZK","order_id":"CRM-8812",
     "consent":{"ad_user_data":"GRANTED"},
     "user_identifiers":[{"hashed_email":"<sha256hex>"},{"hashed_phone_number":"<sha256hex>"}]}]}
  ```
- Hashing/normalization (shared by ECL, EC for web, Customer Match): SHA-256 → lowercase hex (64 chars) of UTF-8 for email, phone, first name, last name, street address; do **not** hash country, state, city, postal code. Trim, lowercase, phone in E.164. Email: for `gmail.com`/`googlemail.com` only, remove all dots and the `+suffix` in the local part; other domains only trim+lowercase. Wrongly normalized data is accepted but never matches.
- Reporting: conversions are attributed to the **impression date of the original click**, not upload date nor `conversion_date_time`. Up to 3 h to appear (last click), longer for DDA.
- Errors (offline clicks/ECL): `NO_CONVERSION_ACTION_FOUND` (action disabled / not owned by `customer_id`, or gclid belongs to account without access – verify with `click_view` filtered by `click_view.gclid` + `segments.date`), `INVALID_CONVERSION_ACTION_TYPE`, `CUSTOMER_NOT_ENABLED_ENHANCED_CONVERSIONS_FOR_LEADS`, `DUPLICATE_ORDER_ID`, `CLICK_NOT_FOUND` (warning; counted as successful; normal for non-Google-Ads clicks e.g. SA360/DV360; else wrong uploader, tagging, hashing, or serving account not accepted data terms), `INVALID_CUSTOMER_FOR_CLICK` (must be the conversion account at click time), `EVENT_NOT_FOUND`, `DUPLICATE_CLICK_CONVERSION_IN_REQUEST`, `CLICK_CONVERSION_ALREADY_EXISTS` (same click+time+action; ignore on retry, or shift `conversion_date_time` for a genuinely new conversion), `EXPIRED_EVENT` (click older than lookback; use action with longer window), `CONVERSION_PRECEDES_EVENT`, `USER_PERMISSION_DENIED` (wrong customer_id).

### Enhanced conversions for web (API)
- Tag sends gclid + order ID; you upload hashed user data later (within 24 h of the conversion) as `ConversionAdjustment{adjustment_type: ENHANCEMENT}` via `ConversionAdjustmentUploadService.UploadConversionAdjustments`.
- Requirements: `accepted_customer_data_terms`; action type `WEBPAGE` with "Turn on enhanced conversions" checked in UI; `order_id` must equal the tag's transaction ID (enhancements must use order_id, not gclid pair); optional `gclid_date_time_pair`, `user_agent` (original request UA), up to 5 `user_identifiers`. `restatement_value` is ignored on ENHANCEMENT – send a separate RESTATEMENT.
- Errors: `CONVERSION_NOT_FOUND` (not a conversion of that conversion customer, or click used gbraid/wbraid – ECW unsupported there), `CUSTOMER_NOT_ACCEPTED_CUSTOMER_DATA_TERMS`, `CONVERSION_ALREADY_ENHANCED` (one enhancement per order_id+action), `CONVERSION_ACTION_NOT_ELIGIBLE_FOR_ENHANCEMENT`.

### Conversion adjustments
- `UploadConversionAdjustments{customer_id, conversion_adjustments[], partial_failure: true, job_id}`; `adjustment_type`: `RETRACTION` (remove), `RESTATEMENT` (new value in `restatement_value.adjusted_value`), `ENHANCEMENT`.
- Supported action types: `SALESFORCE`, `UPLOAD_CLICKS`, `WEBPAGE` (else `INVALID_CONVERSION_ACTION_TYPE`). Works with GCLID and GBRAID, **not WBRAID**.
- Identify by `order_id` (recommended; required for WEBPAGE or if the original had one – else `MISSING_ORDER_ID_FOR_WEBPAGE` / `CONVERSION_NOT_FOUND`) or `gclid_date_time_pair{gclid, conversion_date_time}`.
- Wait 4–6 h after creating the conversion action (`TOO_RECENT_CONVERSION_ACTION`). Only the account that manages the action can adjust (`NO_CONVERSION_ACTION_FOUND`). Never-imported or discarded (invalid/spam) conversions → `CONVERSION_NOT_FOUND`.
- You can't move a conversion to another action: RETRACT it, then upload a new conversion (same timestamp is fine).
  ```json
  {"customer_id":"1234567890","partial_failure":true,"conversion_adjustments":[{
    "conversion_action":"customers/1234567890/conversionActions/555","order_id":"CRM-8812",
    "adjustment_type":"RESTATEMENT","adjustment_date_time":"2026-10-05 09:00:00+02:00",
    "restatement_value":{"adjusted_value":900,"currency_code":"CZK"}}]}
  ```

### Call conversions
- `UploadCallConversions` (REST `POST /v25/customers/{cid}:uploadCallConversions`), `CallConversion{conversion_action (type UPLOAD_CALLS, ENABLED), caller_id E.164 e.g. "+420601123456", call_start_date_time, conversion_date_time (after the call), conversion_value ≥0, currency_code, custom_variables, consent{ad_user_data}}`; `partial_failure = true`.
- `customer_id` must be the conversion customer (`INVALID_CUSTOMER_FOR_CALL`); tracking must have been enabled at call time. Retry rules: `TOO_RECENT_CONVERSION_ACTION` → wait 6 h; `TOO_RECENT_CALL` → wait 12 h. `DUPLICATE_CALL_CONVERSION_IN_REQUEST`. Calls to a manually copied forwarding number or mobile click-to-call without a Google forwarding number can't be recorded.

### Conversion value rules
- `ConversionValueRule`: up to **two** conditions among `audience_condition{user_lists, user_interests}` (any match), `device_condition{device_types}`, `geo_location_condition{geo_target_constants, geo_match_type, excluded_*}`, `itinerary_condition` (allowlist). No condition = fallback rule. `action{operation, value}`: ADD (>0), MULTIPLY (0.5–10 inclusive), SET (>0, only in special sets). Rules are invisible in UI until placed in a set.
- `ConversionValueRuleSet`: `conversion_value_rules[]` (evaluated in order, first match wins), `dimensions` (1–2 of GEO_LOCATION, DEVICE, AUDIENCE, NO_CONDITION; rules may only use listed dimensions; first = `segments.conversion_value_rule_primary_dimension`), `attachment_type` CUSTOMER or CAMPAIGN (+`campaign`), `conversion_action_categories` (empty = all, or exactly one of STORE_VISIT/STORE_SALE; create-only). NO_CONDITION must be alone and only with a store category. A rule may belong to only one ENABLED/PAUSED set (`DATA_CONSTRAINT_VIOLATION`); a set must keep ≥1 enabled/paused rule; set status is read-only (PAUSED only if all rules paused).
- Precedence: campaign-level sets override customer-level; category match; most precise geo; audience ties → MULTIPLY beats ADD, highest multiplier wins.
- Reporting: `metrics.conversions_value` already includes adjustments; `segments.conversion_value_rule_primary_dimension` = NO_RULE_APPLIED / ORIGINAL / GEO_LOCATION / DEVICE / AUDIENCE / NO_CONDITION.

### Custom variables, diagnostics, reporting
- `ConversionCustomVariableService` create `{name (unique), tag}`; status after create ENABLED or ACTIVATION_NEEDED. In uploads `custom_variables[{conversion_custom_variable, value}]` (not with braids, not with ECL user data).
- Offline data diagnostics: `offline_conversion_upload_client_summary` and `offline_conversion_upload_conversion_action_summary` – `status` (EXCELLENT target, NEEDS_ATTENTION, NO_RECENT_UPLOADS…), `successful_event_count`/`total_event_count`/`pending_event_count` (last full day), `alerts`, `daily_summaries` (7 days), `job_summaries` (7 latest jobs), one row per `client` (GOOGLE_ADS_API, GOOGLE_ADS_WEB_CLIENT…). Pending can take up to 24 h. Query with the same `customer_id` used for uploads; CACT clients may return nothing – query the manager. A successful import ≠ attribution; some dropped conversions can't be recovered.
- UI→API: "(by conv. time)" columns = `*_by_conversion_date`, "(current model)" = `current_model_attributed_*`, Store visits = `metrics.all_conversions_from_store_visit`. Adding `segments.conversion_action` splits rows per action and drops rows with zero conversions. UI custom columns are not available in the API.

Zdroj: https://developers.google.com/google-ads/api/docs/conversions/overview · https://developers.google.com/google-ads/api/docs/conversions/categories · https://developers.google.com/google-ads/api/docs/conversions/getting-started · https://developers.google.com/google-ads/api/docs/conversions/upload-offline · https://developers.google.com/google-ads/api/docs/conversions/legacy_oci_guide · https://developers.google.com/google-ads/api/docs/conversions/upload-online · https://developers.google.com/google-ads/api/docs/conversions/upload-calls · https://developers.google.com/google-ads/api/docs/conversions/upload-adjustments · https://developers.google.com/google-ads/api/docs/conversions/conversion-value-rules · https://developers.google.com/google-ads/api/docs/conversions/conversion-custom-variables · https://developers.google.com/google-ads/api/docs/conversions/goals/overview · https://developers.google.com/google-ads/api/docs/conversions/goals/customer-goals · https://developers.google.com/google-ads/api/docs/conversions/goals/campaign-goals · https://developers.google.com/google-ads/api/docs/conversions/goals/lifecycle-goals · https://developers.google.com/google-ads/api/docs/conversions/upload-summaries · https://developers.google.com/google-ads/api/docs/conversions/reporting · https://developers.google.com/google-ads/api/docs/conversions/troubleshooting · https://developers.google.com/google-ads/api/docs/best-practices/quotas · https://developers.google.com/google-ads/api/reference/rpc/v25/Consent

---

## 3. Audiences & Customer Match

### Which object for which campaign
- `UserList` (audience segments: remarketing, Customer Match, logical…) targeted directly with `AdGroupCriterion.user_list` / `CampaignCriterion.user_list`: Display, Search, Video, Hotel, Standard Shopping.
- `Audience` resource (`AudienceService.MutateAudiences`) – reusable bundle of segments + demographics + exclusions: **Performance Max** (as signal on `AssetGroupSignal.audience`), **Demand Gen** and **App** (`AdGroupCriterion.audience.audience`).
- For Demand Gen/App ad groups using `Audience`, `AdGroup.audience_setting.use_audience_grouped = true` **must be set at ad group creation and cannot be changed** (criterion create fails otherwise). `Campaign.audience_setting.use_audience_grouped` can be set only at campaign creation; then campaign-level exclusion criteria of segments/demographics error out.
- `Audience` rules: unique name; dimensions `audience_segments` (UserListSegment, UserInterestSegment, LifeEventSegment, DetailedDemographicSegment, CustomAudienceSegment), AgeDimension, GenderDimension, HouseholdIncomeDimension, ParentalStatusDimension – one per type; no duplicate segments; `exclusion_dimension` accepts **only UserListSegment**. Errors: AUDIENCE_SEGMENT_NOT_FOUND, DIMENSION_INVALID, DUPLICATE_AUDIENCE_SEGMENT, NAME_ALREADY_IN_USE, TOO_MANY_DIMENSIONS_OF_SAME_TYPE, TOO_MANY_SEGMENTS.
  ```json
  {"operations":[{"create":{"name":"Buyers + in-market",
    "dimensions":[{"audience_segments":{"segments":[{"user_list":{"user_list":"customers/1/userLists/77"}},
                                                    {"user_interest":{"user_interest_category":"customers/1/userInterests/80432"}}]}}],
    "exclusion_dimension":{"exclusions":[{"user_list":{"user_list":"customers/1/userLists/78"}}]}}}]}
  ```

### User list types
- `crm_based_user_list` (Customer Match), `rule_based_user_list` (tag/URL rules), `logical_user_list` (AND of rules over other lists/interests), `basic_user_list` (conversion/remarketing actions), `lookalike_user_list`, `similar_user_list` (output-only, sunset). Custom segments are a separate `CustomAudience` resource.
- Only the account (or data partner) that created a list can modify it; others see it read-only. User lists aren't supported in test accounts (auto-closed). GA-linked audiences show as REMARKETING / RULE_BASED lists – identify by name. `membership_life_span` is ignored for logical and rule-based lists.
- One account-level Google tag per account (auto-created); `RemarketingAction` returns tag snippets. Built-in `url__` parameter for URL rules (no tag edits needed); custom parameters need tag changes.

### Targeting, observation & exclusions
- `targeting_setting.target_restrictions[{targeting_dimension, bid_only}]`: `bid_only=true` = Observation (no reach restriction, bid adjustments only); `false` = Targeting (restricts traffic). Omitted dimension = Targeting. Dimensions: AUDIENCE, TOPIC, GENDER, AGE_RANGE, PLACEMENT, PARENTAL_STATUS, INCOME_RANGE (KEYWORD is always targeting). For Search/Shopping audience layering the docs recommend `AUDIENCE` with `bid_only=true`. UI-created Shopping campaigns may omit AUDIENCE → API treats it as Targeting; set it explicitly.
- Setting `target_restrictions` **replaces the whole list** – missing entries are removed. Use `target_restriction_operations[{operator: ADD|REMOVE, target_restriction}]` for incremental changes. An ad group can't have `targeting_setting` while its campaign has one (clear with empty list in `update_mask`).
- Exclusion: `AdGroupCriterion{user_list, negative: true}` or negative `CampaignCriterion`. Positive user lists can't be on both campaign and ad group level of the same campaign – to move to campaign level, first remove all `ad_group_criterion` of type USER_LIST in the campaign (incl. paused ad groups). Campaign-level positive user list targeting: Search only; on Display campaigns a campaign-level `user_list` criterion must be negative.
- In Search/Shopping, user list criteria don't support `url_custom_parameters`, `tracking_url_template`, `final_urls`, `final_mobile_urls`.
- Rule-based list serving thresholds: ≥100 active users (Display), ≥1,000 (Search). Example structure: `rule_based_user_list.flexible_rule_user_list{inclusive_rule_operator: AND, inclusive_operands[{rule{rule_item_groups[{rule_items[{name:"url__", string_rule_item{operator: CONTAINS, value:"example.com/kosik"}}]}]}, lookback_window_days: 30}]}`, `prepopulation_status: REQUESTED` to backfill past visitors.
- Logical lists: `logical_user_list.rules[{operator: ALL|ANY|NONE, rule_operands[{user_list}]}]`, rules ANDed, nestable; revoked-access lists count as empty. CRM lists combine only with CRM lists (and only FIRST_PARTY sourced).
- Performance: `ad_group_audience_view`, `campaign_audience_view` (wait ≥2 weeks before bid changes).

### Custom segments (`CustomAudience`)
- `CustomAudienceService.MutateCustomAudiences{name, description, type, status: ENABLED, members[]}`. New audiences: type `AUTO` (or `SEARCH`); `INTEREST` and `PURCHASE_INTENT` can't be created anymore. Members: KEYWORD (`keyword`), URL (`url`), APP (`app` package name) – user matching any member qualifies.
- Display/Video: `CampaignCriterion.custom_audience` / `AdGroupCriterion.custom_audience`. PMax/Demand Gen: wrap in `CustomAudienceSegment` inside an `Audience`. Recommendation `CUSTOM_AUDIENCE_OPT_IN`.

### Lookalike segments
- **Demand Gen only** (elsewhere "Eligible – Limited", no effect). `lookalike_user_list{seed_user_list_ids, expansion_level: NARROW|BALANCED|BROAD (required), country_codes}`. Duplicates (same seeds+level+countries) → `UserListError.DUPLICATE_LOOKALIKE`. Seed needs a minimum of active matched users (guide inconsistent: 100 vs 1,000 – check `size_range_for_display/search`). Refresh every 1–2 days; becomes Ineligible silently (up to 3 days) when the seed shrinks. Create 2–3 days before launch. Target via `UserListSegment` in an `Audience` with `use_audience_grouped`.

### Customer Match – eligibility & platform status
- Account needs good policy-compliance and payment history (Customer Match policy).
- **Since April 1, 2026, `OfflineUserDataJobService`/`UserDataService` Customer Match requests fail with `NotAllowlistedError.CUSTOMER_NOT_ALLOWLISTED_FOR_THIS_FEATURE` if the Google Cloud project (or legacy developer token) had no Customer Match activity between Oct 1, 2025 and Mar 31, 2026.** New integrations → Data Manager API. Legacy developer token deprecated Sep 9, 2026 (replaced by Cloud projects; the historical-activity restriction still applies).
- Contact info must belong to a Google Account; corporate (Workspace) accounts can't be targeted. Lists serve only above a minimum of active users – upload ≥5,000 members.

### Customer Match – list creation
- `UserListService.MutateUserLists` with `crm_based_user_list{upload_key_type, data_source_type, app_id}`. `upload_key_type` (required, one per list, no mixing): CONTACT_INFO (recommended; email/phone/address in any mix), CRM_ID (`third_party_user_id`), MOBILE_ADVERTISING_ID (IDFA/AAID in `mobile_id`; `app_id` required). `data_source_type` default FIRST_PARTY; THIRD_PARTY_CREDIT_BUREAU / VOTER_FILE / PARTNER_DATA allowlist-only and not combinable.
- `membership_life_span` ≤ **540** days (default 540); `membership_status` OPEN/CLOSED.
  ```json
  {"operations":[{"create":{"name":"CRM buyers 2026","membership_life_span":540,
    "crm_based_user_list":{"upload_key_type":"CONTACT_INFO","data_source_type":"FIRST_PARTY"}}}]}
  ```
- Usable in Search, Display, Display Expansion on Search, Shopping, Video, Demand Gen (via `Audience`), PMax (signal).

### Customer Match – OfflineUserDataJob workflow (preferred)
1. `OfflineUserDataJobService.CreateOfflineUserDataJob{job{type: CUSTOMER_MATCH_USER_LIST, customer_match_user_list_metadata{user_list, consent{ad_user_data, ad_personalization}}}}`. Consent required for create jobs (not for remove). If either consent is DENIED → `OfflineUserDataJobError.CUSTOMER_NOT_ACCEPTED_CUSTOMER_DATA_TERMS`. Users lacking consent info: put them in a separate job without the consent field; users who denied: remove job. `external_id` must be unique per job (`EXTERNAL_UPDATE_ID_ALREADY_EXISTS`).
2. `AddOfflineUserDataJobOperations{resource_name, enable_partial_failure: true, operations[{create|remove: UserData{user_identifiers[]}} | {remove_all: true}]}` – recommended ~10,000 identifiers per call, **max 100,000 identifiers per request**; ≤20 identifiers per `UserData` (`TOO_MANY_USER_IDENTIFIERS`); each `UserIdentifier` holds exactly one identifier (several in one object lowers match rate). Address needs hashed first+last name + `country_code` + `postal_code`, else unmatched.
3. Repeat while the job is PENDING (no op limit; recommended ≤1,000,000 ops/job; one big job beats many small ones).
4. `RunOfflineUserDataJob` – **within 5 days of creation** or the job expires. Returns a long-running operation.
5. Poll `offline_user_data_job.status` (10 min–24 h) → SUCCESS; then `operation_metadata.match_rate_range` (0 before completion); errors in `offline_user_data_job.failure_reason` (no per-identifier match info).
  ```json
  {"enable_partial_failure":true,"operations":[{"create":{"user_identifiers":[
    {"hashed_email":"<sha256hex>"},{"hashed_phone_number":"<sha256hex>"},
    {"address_info":{"hashed_first_name":"<sha>","hashed_last_name":"<sha>","country_code":"CZ","postal_code":"60200"}}]}}]}
  ```
- Rules: never mix `create` and `remove` in one job (`CONFLICTING_OPERATION`); `remove_all` must be the **first** operation and may be followed by creates (full replace) else `INVALID_OPERATION_ORDER`; remove_all runs hourly, may take up to 24 h. One identifier suffices to remove a user. Don't run two RUNNING jobs on the same list or edit it in UI meanwhile (`CONCURRENT_MODIFICATION`). With partial failure off (default) one bad op fails the whole request; if all ops fail with partial failure on, running the job "succeeds" with nothing. Maximize ops per request to avoid `RESOURCE_EXHAUSTED`.
- `UserDataService.UploadUserData` (small/sporadic updates): max **10 operations and 100 user_identifiers per request**; `customer_match_user_list_metadata` required (with consent for creates); consent DENIED → `received_operations_count = 0` (silently not processed). Takes hours to populate.
- Size/match: `user_list.size_for_*` shows 0 until ≥100 members, then rounded to 2 significant digits; UI shows active users only; uploading more often than every 12 h may keep UI "In Progress". Match rate counts all matched Google Accounts; size counts reachable ones. Remove list with `UserListService` remove. Recommendation `REFRESH_CUSTOMER_MATCH_LIST` flags lists not updated in 90 days.

Zdroj: https://developers.google.com/google-ads/api/docs/remarketing/overview · https://developers.google.com/google-ads/api/docs/remarketing/audiences · https://developers.google.com/google-ads/api/docs/remarketing/audience-segments/getting-started · https://developers.google.com/google-ads/api/docs/remarketing/audience-segments/website-visitors · https://developers.google.com/google-ads/api/docs/remarketing/audience-segments/multiple-user-lists · https://developers.google.com/google-ads/api/docs/remarketing/audience-segments/customer-match/get-started · https://developers.google.com/google-ads/api/docs/remarketing/audience-segments/customer-match/manage · https://developers.google.com/google-ads/api/docs/remarketing/audience-segments/customer-match/troubleshoot · https://developers.google.com/google-ads/api/docs/remarketing/audience-segments/custom-audiences · https://developers.google.com/google-ads/api/docs/remarketing/audience-segments/lookalike-audiences · https://developers.google.com/google-ads/api/docs/targeting/targeting-settings · https://developers.google.com/google-ads/api/docs/best-practices/quotas

---

## 4. Planning, insights & recommendations

### KeywordPlanIdeaService (Keyword Planner)
- Methods: `GenerateKeywordIdeas`, `GenerateKeywordHistoricalMetrics`, `GenerateKeywordForecastMetrics`, `GenerateAdGroupThemes`. Nothing is persisted (no KeywordPlan objects needed). Stricter rate limits for both basic and standard access: **1 request/s per customer ID** for ideas, historical and forecast; 2/s for ad group themes. Results are stable for hours/days → cache; volumes refresh monthly (previous month's data).
- **Ideas** seeds: `keyword_seed` (1–20 keywords), `url_seed` (one page; expands to same domain if no hits; link contents ignored), `keyword_and_url_seed` (1–20 keywords + URL; more ideas than URL alone), `site_seed` (domain, up to 250,000 ideas). Targeting: `language` (one `languageConstants/{id}`; IDs from the Codes & formats table – guide samples use 1000 = English), `geo_target_constants` (≤10, empty = all; samples use 2840 = USA), `keyword_plan_network` (GOOGLE_SEARCH or GOOGLE_SEARCH_AND_PARTNERS), `include_adult_keywords`, `keyword_annotation`, `historical_metrics_options`. Paged: up to 10,000 results/page – always follow `next_page_token` (pages may be short).
  ```json
  {"customer_id":"1234567890","language":"languageConstants/1021",
   "geo_target_constants":["geoTargetConstants/2203"],"keyword_plan_network":"GOOGLE_SEARCH",
   "keyword_and_url_seed":{"keywords":["jídelní stůl"],"url":"https://example.cz/stoly"},"page_size":1000}
  ```
- **Historical metrics**: up to 10,000 keywords/request; `historical_metrics_options.year_month_range` (default last 12 months), `include_average_cpc` (legacy `average_cpc_micros`). Returns `avg_monthly_searches`, `monthly_search_volumes` (up to 4 years), `competition`, `competition_index` (0–100, null if insufficient data), `low_top_of_page_bid_micros` (20th pct), `high_top_of_page_bid_micros` (80th pct). Close variants are merged (e.g. "car"/"cars") → fewer results than inputs; see `close_variants`.
- **Forecast** (v24+ shape): `campaign: CampaignToForecast{bidding_strategy (manual_cpc_bidding_strategy{max_cpc_bid_micros, daily_budget_micros} | maximize_clicks_bidding_strategy{max_cpc_bid_ceiling_micros, daily_target_spend_micros} | maximize_conversions_bidding_strategy{daily_target_spend_micros}), geo_target_constants, language_constants, ad_groups[{keywords[{text, match_type}]}]}`, `forecast_period` (start in future, end ≤1 year; default next Sunday–Saturday in account tz). Network defaults to Google Search; negative keywords, per-ad-group/keyword bids and custom conversion_rate were removed in v24. Returned: `cost_micros` always; `clicks`/`average_cpc_micros` only for Manual CPC / Max Clicks; `conversions`/`average_cpa_micros` only for Max Conversions. Forecast in a related account (quality score & creatives influence results); assumes settings constant over the window.
- **GenerateAdGroupThemes**: groups keywords into suggested (existing) ad groups with match types; paginated. Detailed limits not stated in the guide.

### Recommendations & optimization score
- `customer.optimization_score`, `campaign.optimization_score`; `metrics.optimization_score_uplift` (whole-set estimate, not a sum) and `metrics.optimization_score_url`, segmentable by `segments.recommendation_type`.
- Read with GAQL `FROM recommendation` (details in type-specific field, e.g. `campaign_budget_recommendation`); `impact.base_metrics`/`potential_metrics` (impressions, clicks, cost_micros, conversions, all_conversions, video_views) – availability varies, check presence.
- Recommendations can change daily or several times a day; **resource_name can become stale → act right after retrieval**.
- `RecommendationService.ApplyRecommendation` (works on active or dismissed recs) with optional `apply_parameters` per type to override suggested values (types not in the union ignore parameters); `DismissRecommendation`. Use `partial_failure` for batches.
  ```json
  {"operations":[{"resource_name":"customers/1/recommendations/abc",
    "campaign_budget":{"new_budget_amount_micros":"50000000"}}],"partial_failure":true}
  ```
- "Fully supported" types (~55, see guide table): budgets (CAMPAIGN_BUDGET, FORECASTING_CAMPAIGN_BUDGET, MARGINAL_ROI_CAMPAIGN_BUDGET, MOVE_UNUSED_BUDGET), bidding opt-ins and target tweaks (*_OPT_IN, SET_/RAISE_/LOWER_TARGET_*, FORECASTING_SET_TARGET_*), keywords/ads (KEYWORD, USE_BROAD_MATCH_KEYWORD – KEYWORD_MATCH_TYPE deprecated, TEXT_AD, RESPONSIVE_SEARCH_AD*, OPTIMIZE_AD_ROTATION), assets (CALLOUT_ASSET, SITELINK_ASSET, CALL_ASSET, LEAD_FORM_ASSET, DYNAMIC_IMAGE_EXTENSION_OPT_IN), PMax/Demand Gen strength & migrations, SHOPPING_* feed fixes, DISPLAY_EXPANSION_OPT_IN, SEARCH_PARTNERS_OPT_IN, CUSTOM_AUDIENCE_OPT_IN, REFRESH_CUSTOMER_MATCH_LIST, IMPROVE_GOOGLE_TAG_COVERAGE.
- **Auto-apply**: `RecommendationSubscriptionService` – `RecommendationSubscription{type, status: ENABLED}`; supported only for ENHANCED_CPC_OPT_IN, KEYWORD, KEYWORD_MATCH_TYPE, LOWER_TARGET_ROAS, MAXIMIZE_CLICKS_OPT_IN, OPTIMIZE_AD_ROTATION, RAISE_TARGET_CPA, RESPONSIVE_SEARCH_AD, RESPONSIVE_SEARCH_AD_IMPROVE_AD_STRENGTH, SEARCH_PARTNERS_OPT_IN, SET_TARGET_CPA, SET_TARGET_ROAS, TARGET_CPA_OPT_IN, TARGET_ROAS_OPT_IN, USE_BROAD_MATCH_KEYWORD. Inspect via `recommendation_subscription`; see what was auto-applied in `change_event` with `client_type = 'GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION'`. (To prevent unwanted auto-apply, check/disable subscriptions; UI auto-apply settings for other types are not exposed.)
- **GenerateRecommendations** (for campaigns being built): `customer_id`, `advertising_channel_type` SEARCH or PERFORMANCE_MAX, `recommendation_types`, plus type-specific inputs: CAMPAIGN_BUDGET needs `asset_group_info`, `final_url`, `bidding_info.bidding_strategy_type` (+ for Search `country_code`, `language_code`, `positive_location_id`/`negative_location_id`, `ad_group_info.keywords`, target IS info if TARGET_IMPRESSION_SHARE; optional `budget_info`, `merchant_center_account_id` for retail PMax); KEYWORD needs `seed_info`; bidding opt-ins/SET_TARGET_* need `conversion_tracking_status` + `bidding_info`; SITELINK_ASSET needs `campaign_sitelink_count` (returned object has empty lists = "add a sitelink"). Empty result is normal (insufficient data or already optimal).

### ReachPlanService (YouTube/video reach)
- Allowlist only; **both** the developer token and the Google Cloud project number must be allowlisted for ReachPlanService. `customer_id` must be accessible to the OAuth user (planning can use a placeholder account under your manager).
- Flow: `ListPlannableLocations` → `ListPlannableProducts(plannable_location_id)` (product codes e.g. TRUEVIEW_IN_STREAM, BUMPER; per-product `plannable_targeting`; values change – fetch live) → `GenerateReachForecast{customer_id, campaign_duration{duration_in_days 1–90}, planned_products[{plannable_product_code, budget_micros, advanced_product_targeting}], currency_code, cookie_frequency_cap_setting, min_effective_frequency, targeting{plannable_location_id, age_range (e.g. AGE_RANGE_18_65_UP), genders, devices, network, audience_targeting}, customer_reach_group (required if audience_targeting set)}`.
- Response `reach_curve.reach_forecasts[]{cost_micros, forecast{on_target_reach, total_reach, on_target_impressions, total_impressions, …}, planned_product_reach_forecasts[]}`. Mass caching of curves is prohibited. DEMAND_GEN products need expected conversion rates from `GenerateConversionRates` (prefer surface-specific suggestions).

### AudienceInsightsService
- Allowlist + eligibility review (Insights Finder access, planning use case, audits). Rate limits: `GenerateAudienceCompositionInsights` and `GenerateSuggestedTargetingInsights` ~200 requests/day per customer ID; `GenerateTargetingSuggestionMetrics` 2 QPS per Cloud project.
- Methods: `ListInsightsEligibleDates`, `ListAudienceInsightsAttributes` (get attribute IDs first; KNOWLEDGE_GRAPH needs `query_text`), `GenerateAudienceDefinition` (free text → attributes), `GenerateSuggestedTargetingInsights`, `GenerateTargetingSuggestionMetrics` (YouTube reach), `GenerateAudienceCompositionInsights` (country required; `data_month` or last 30 days), `GenerateAudienceOverlapInsights` (country + primary attribute; dims age, gender, affinity, in-market), `GenerateInsightsFinderReport` (returns UI link).

### BenchmarksService
- Allowlist only; must use a **client** customer ID (manager IDs return no customer metrics).
- `ListBenchmarksAvailableDates` (`supported_dates` vs narrower `supported_dates_for_all_metrics` – share of voice/spend and source averages only there), `ListBenchmarksLocations`, `ListBenchmarksProducts` (product_code, marketing objective AWARENESS/CONSIDERATION/ACTION), `ListBenchmarksSources` (INDUSTRY_VERTICAL | CATEGORY).
- `GenerateBenchmarksMetrics{customer_id, location, benchmarks_source, product_filter, date_range, breakdown_definition.date_breakdown WEEK (Sun–Sat)|MONTH|QUARTER (full periods), currency_code, supplemental_data: [PERCENTILE_DATA], category_filter}`. Percentile tiers (DEVELOPING…MARKET_LEADER) need `all_advertisers = true` + category_filter + PERCENTILE_DATA. Errors: MAX_QUERY_COMPLEXITY_EXCEEDED, NO_METRICS_FOUND.

Zdroj: https://developers.google.com/google-ads/api/docs/keyword-planning/overview · https://developers.google.com/google-ads/api/docs/keyword-planning/generate-keyword-ideas · https://developers.google.com/google-ads/api/docs/keyword-planning/generate-historical-metrics · https://developers.google.com/google-ads/api/docs/keyword-planning/generate-forecast-metrics · https://developers.google.com/google-ads/api/docs/keyword-planning/generate-ad-group-themes · https://developers.google.com/google-ads/api/docs/recommendations · https://developers.google.com/google-ads/api/docs/reach-forecasting/concepts · https://developers.google.com/google-ads/api/docs/reach-forecasting/authentication · https://developers.google.com/google-ads/api/docs/reach-forecasting/media-plan · https://developers.google.com/google-ads/api/docs/reach-forecasting/generate-curve · https://developers.google.com/google-ads/api/docs/insights/audience-insights · https://developers.google.com/google-ads/api/docs/benchmarks/overview · https://developers.google.com/google-ads/api/docs/best-practices/quotas

---

## 5. Experiments, labels, shared sets, change history, previews, billing

### Experiments – types & lifecycle
- `ExperimentType` → workflow: System-managed `SEARCH_CUSTOM`, `DISPLAY_CUSTOM`, `HOTEL_CUSTOM`, `YOUTUBE_CUSTOM` (UI: custom Video / Demand Gen), `PMAX_REPLACEMENT_SHOPPING`; Intra-campaign `ADOPT_AI_MAX`, `ADOPT_BROAD_MATCH_KEYWORDS`, `PMAX_TEXT_CUSTOMIZATION_FINAL_URL_EXPANSION`; Asset optimization `OPTIMIZE_ASSETS`; Campaign Mix `COMPARE_CAMPAIGNS` (allowlist).
- Status flow: SETUP (system-managed only) → INITIATED (after ScheduleExperiment) → ENABLED → HALTED (End) / PROMOTED / GRADUATED. Other workflows create experiment + arms directly ENABLED in one `GoogleAdsService.Mutate` with temporary IDs.
- **One experiment per campaign at a time.** Best practice: ≥4 weeks, ignore first 1–2 weeks for smart bidding, 50/50 split fastest, schedule start 3–7 days ahead for ad review.

### System-managed (draft-based) experiments
1. `ExperimentService` create `{name (unique), suffix (appended to treatment names), type, status: SETUP, start_date, end_date, sync_enabled}` (`sync_enabled` true copies base-campaign edits into the treatment during the run; default off).
2. `ExperimentArmService.MutateExperimentArms` – **all arms in one request, no partial failure**: exactly one control arm (`control: true`, `campaigns: [one existing campaign]`) + ≥1 treatment arms; `traffic_split` sums to 100. Treatment arms auto-create draft campaigns listed in `in_design_campaigns` (use `response_content_type: MUTABLE_RESOURCE` to get them).
   ```json
   {"operations":[{"create":{"experiment":"customers/1/experiments/9","name":"control","control":true,"traffic_split":50,"campaigns":["customers/1/campaigns/2"]}},
                  {"create":{"experiment":"customers/1/experiments/9","name":"tCPA test","control":false,"traffic_split":50}}],
    "response_content_type":"MUTABLE_RESOURCE"}
   ```
3. Edit the in-design campaign like a normal campaign (≥1 change required before scheduling). Drafts are only visible with `PARAMETERS include_drafts = true` in GAQL (`SELECT experiment_arm.in_design_campaigns FROM experiment_arm WHERE … PARAMETERS include_drafts = true`).
4. `ScheduleExperiment` – async long-running operation; materializes campaigns that serve from `start_date`.
5. Finish: `EndExperiment` (sync; treatment stops, not deleted, nothing applied), `PromoteExperiment` (async; copies treatment changes into control, treatment stops), `GraduateExperiment` (sync; treatment becomes a standalone campaign, control unchanged; requires `campaign_budget_mappings[{experiment_campaign, campaign_budget}]` – a new budget for the graduated campaign).
- `PMAX_REPLACEMENT_SHOPPING`: exactly 2 arms; control = Shopping campaign; treatment `campaigns` empty (auto PMax draft) or an existing PMax campaign; cannot be promoted; ignore first 7 days. `YOUTUBE_CUSTOM`: max 10 arms; `asset_testing_info` on arm for asset tests.
- Async errors: the LRO only signals failure (`error` summary). Get details with `ExperimentService.ListExperimentAsyncErrors{resource_name, page_size}` (REST `GET /v25/customers/{cid}/experiments/{id}:listExperimentAsyncErrors?pageSize=100`).

### Intra-campaign, asset optimization, campaign mix
- Intra-campaign: experiment (status ENABLED) + control & treatment arms in one Mutate. ADOPT_AI_MAX / ADOPT_BROAD_MATCH_KEYWORDS: both arms reference the same campaign, **split must be 50/50**; ADOPT_AI_MAX additionally needs a `CampaignOperation` update (`ai_max_setting.enable_ai_max`, asset automation settings) with field mask. PMAX_TEXT_CUSTOMIZATION_FINAL_URL_EXPANSION: only the treatment arm sets `campaigns`; custom split summing to 100. Promote only for the two Search types (async); Graduate only for the PMax type (sync, needs `campaign_budget_mappings`). Reporting only via `FROM experiment`.
- OPTIMIZE_ASSETS (PMax): one Mutate with new Asset (temp id) → Experiment (`optimize_assets_experiment.optimize_assets_experiment_subtype`: COMPARE_ASSETS, ADD_ASSETS_TO_ASSETLESS_RETAIL, ADD_VIDEO_ASSETS_TO_VIDEOLESS) → 2 arms with `asset_groups[{asset_group (same base group in both), asset_group_assets[{asset, field_type}]}]` → `AssetGroupAsset` links. One asset group per experiment; no identical (asset, field_type) in both arms. Graduate pauses the base campaign and spins the treatment into a new campaign.
- COMPARE_CAMPAIGNS: ≤5 arms, any campaigns per arm, all types except Hotel, integer splits ≥1%, no two arms with identical campaign sets, uses existing campaigns. Graduate pauses all other arms' campaigns.

### Experiment reporting
- `FROM experiment`: `metrics.<m>` = treatment, `metrics.control_<m>` = control, plus `<m>_point_estimate` (treatment/control − 1), `<m>_margin_of_error`, `<m>_p_value` for clicks, impressions, cost_micros, conversions, cost_per_conversion, conversion_value, conversion_value_per_cost; conversions significance uses `conversions_absolute_change_*`. Significantly better if point_estimate − margin > 0.
- System-managed only: `campaign.experiment_type` BASE vs EXPERIMENT (compute stats yourself). Metrics stay with their original campaigns after promotion/graduation.

### Labels
- `LabelService.MutateLabels{name, text_label{background_color, description}}`; attach via `CustomerLabel`, `CampaignLabel`, `AdGroupLabel`, `AdGroupAdLabel`, `AdGroupCriterionLabel` services (one link per entity–label pair).
- `CustomerLabelService`: manager labels client accounts; label must be manager-owned; `customer` is output-only (taken from request `customer_id`); one client per request. `customer_client.applied_labels` shows only caller-owned labels.
- GAQL can filter **only by `label.id`**, not name (resolve via `SELECT label.id FROM label WHERE label.name = '…'`). `campaign.labels` / `ad_group.labels` return resource names. Limits not stated in the guide.

### Shared sets (negative lists etc.)
- `SharedSetService` `{name, type}` → `SharedCriterionService.MutateSharedCriteria` (batch criteria, e.g. `keyword{text, match_type}`) → attach.
- Types: NEGATIVE_KEYWORDS (`CampaignSharedSet`; Search, Display, Shopping, App MULTI_CHANNEL, Local), NEGATIVE_PLACEMENTS (`CampaignSharedSet` or account-level `CustomerNegativeCriterion.placement_list`), ACCOUNT_LEVEL_NEGATIVE_KEYWORDS (only via `CustomerNegativeCriterion.negative_keyword_list`; max 1 per account), BRANDS (campaign `CampaignCriterion.brand_list` include/exclude; ad group positive only), WEBPAGES (allowlist), VERTICAL_ADS_ITEM_GROUP_RULE_LIST, RETAIL_FILTER (v24+, allowlist).
- Limits: **20 shared negative keyword lists per account, 5,000 negative keywords per set** (`ResourceCountLimitExceededError`).
- Manager-owned lists: send with `login-customer-id` = manager; attach in the client via `CustomerNegativeCriterion` referencing the manager's shared set.
  ```json
  {"operations":[{"create":{"campaign":"customers/1/campaigns/2","shared_set":"customers/1/sharedSets/44"}}]}
  ```

### Change history
- `change_event`: `WHERE change_event.change_date_time >= '…' AND change_event.change_date_time <= '…'` within the **last 30 days**, `LIMIT` mandatory (≤10,000; page by last `change_date_time`). Fields: `change_resource_type`, `change_resource_name`, `resource_change_operation`, `changed_fields`, `old_resource`/`new_resource` (CREATE → new only, UPDATE → both), `client_type`, `user_email` (only if visible in UI). Up to 3 min latency. Not all changes are present; **Google Ads Editor changes and criterion-level changes aren't covered** – use change_status.
- `change_status`: `WHERE change_status.last_change_date_time` within **90 days**, `LIMIT ≤10,000`. One row per resource with only the latest status (ADDED/CHANGED/REMOVED), parent rollup, no field values (re-query by resource name).
  ```sql
  SELECT change_event.change_date_time, change_event.client_type, change_event.user_email,
         change_event.change_resource_type, change_event.resource_change_operation, change_event.changed_fields
  FROM change_event
  WHERE change_event.change_date_time >= '2026-10-01' AND change_event.change_date_time <= '2026-10-12'
  ORDER BY change_event.change_date_time DESC LIMIT 1000
  ```

### Shareable previews
- `ShareablePreviewService.GenerateShareablePreviews{shareable_previews[{asset_group | ad_group_ad, preview_type}]}` – supported only for PMax asset groups and certain YouTube video/audio formats (`ad_group_ad` only with YOUTUBE_LIVE_PREVIEW). RSA/RDA → `UNSUPPORTED_AD_TYPE`. Preview URLs can't be iframed (`X-Frame-Options: deny`).

### Billing & invoices (mostly read-only)
- Billing setups, account budgets and invoices via API require **monthly invoicing**. Incentives (`IncentiveService`, `applied_incentive`) are allowlist-only.
- `InvoiceService.ListInvoices{customer_id (serving account), billing_setup, issue_year "2026" (≥2019), issue_month e.g. "SEPTEMBER", include_granular_level_invoice_details}` – read-only; one call per serving account; `login-customer-id` (if set) must be the paying manager; consolidated billing returns all accounts on that billing setup. Errors: YEAR_MONTH_TOO_OLD, NOT_INVOICED_CUSTOMER, ACTION_NOT_PERMITTED. `pdf_url` needs an authenticated GET with the same user's OAuth token. Invoice totals can differ from served cost (late adjustments).
- Account budgets can't be edited directly: `AccountBudgetProposalService` with `proposal_type` CREATE / UPDATE (with `update_mask`) / END (end now) / REMOVE (only before start). One operation per call; Google reviews (typically <1 h); cancel pending by removing the proposal. One active account budget per customer; new budget must start after the current one ends. `proposed_*_date_time` in account timezone; `proposed_spending_limit_micros` or `TimeType` (NOW/FOREVER, INFINITE limit). Read effective limits from `account_budget` (`approved_*`, `adjusted_spending_limit_micros`, `pending_proposal`).
- Local Services Ads management is not covered by these guides (out of scope here).

Zdroj: https://developers.google.com/google-ads/api/docs/experiments/overview · https://developers.google.com/google-ads/api/docs/experiments/system-managed · https://developers.google.com/google-ads/api/docs/experiments/intra-campaign · https://developers.google.com/google-ads/api/docs/experiments/asset-optimization · https://developers.google.com/google-ads/api/docs/experiments/campaign-mix · https://developers.google.com/google-ads/api/docs/experiments/reporting · https://developers.google.com/google-ads/api/docs/experiments/async-errors · https://developers.google.com/google-ads/api/docs/reporting/labels · https://developers.google.com/google-ads/api/docs/targeting/shared-sets · https://developers.google.com/google-ads/api/docs/change-event · https://developers.google.com/google-ads/api/docs/change-status · https://developers.google.com/google-ads/api/reference/rpc/v25/ShareablePreview · https://developers.google.com/google-ads/api/docs/billing/overview · https://developers.google.com/google-ads/api/docs/billing/account-budgets · https://developers.google.com/google-ads/api/docs/billing/invoice


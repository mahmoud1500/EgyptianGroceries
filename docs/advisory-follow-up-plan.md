# Advisory implementation status for PR #19

This document tracks the advisory findings and the remaining review gates. The implementation in this PR is limited to the current branch; nothing here authorizes merging or deployment.

## Implemented in this PR

- [x] Expand smart-search matching to bilingual names, descriptions, ingredients, and allergen fields while keeping fuzzy matching limited to dish names.
- [x] Add search normalization regression tests.
- [x] Use the approved commission base for new orders: food subtotal after promo and loyalty discounts, excluding tax and delivery fees.
- [x] Add a reusable commissionable-food-amount helper for legacy orders whose commission snapshot is missing.
- [x] Preserve non-null historical `commission_due` snapshots rather than silently recalculating old orders.
- [x] Distinguish unknown delivery actual cost from a confirmed zero using `actual_cost_confirmed`; unknown cost/subsidy serializes as `null`.
- [x] Require confirmed actual cost before marking a delivery delivered, and require delivered status plus confirmed cost before marking its cost paid.
- [x] When an eligible delivery is marked delivered, update the related order to `completed` and record the order event in the same database transaction.
- [x] Add focused commission and delivery-cost regression tests.
- [x] Add a backward-compatible startup schema addition for the delivery-cost confirmation flag.

## Remaining work

### P1 — Refund reconciliation (not implemented)

- [ ] Add durable refund-operation records with order/sub-order reference, PaymentIntent, amount/currency, idempotency key, provider refund ID, state, and timestamps.
- [ ] Make retries recoverable if Stripe accepts a refund but local persistence fails.
- [ ] Reconcile refunds created in Stripe Dashboard before computing refundable balances.
- [ ] Test retries/idempotency, external refunds, partial multi-vendor refunds, and database failures.
- **Safety gate:** A PaymentIntent may cover multiple vendor sub-orders. Do not attribute a dashboard-issued refund to a specific sub-order or change refund behavior until allocation rules and Stripe test-mode cases are reviewed.

### P1 — Delivery accounting (partially implemented)

- [x] Unknown actual cost is distinct from a confirmed zero.
- [x] Gate delivered/paid status on actual-cost evidence.
- [x] Synchronize delivery completion with order status and the order event log in one transaction.
- [ ] Add endpoint-level tests for database rollback, cancelled orders, failed/cancelled deliveries, cost corrections, and settlement reconciliation.
- [ ] Decide whether multi-vendor checkouts can share a courier run and how any shared cost is allocated.
- **Safety gate:** Dispatch remains manual. A recorded `paid` status is an application record, not independent proof of a bank/courier payment.

### P1 — Commission accounting (implemented for new orders and missing legacy snapshots)

- [x] Approved base: food subtotal after promo and loyalty discounts; exclude tax and delivery fees.
- [x] Apply the policy to new checkout snapshots and fallback calculations when a legacy snapshot is absent.
- [x] Preserve existing non-null historical snapshots.
- [ ] Add end-to-end checkout tests covering promo discounts, loyalty points, tax, delivery, and vendor-specific rates.
- **Policy note:** Discounts are deducted from the food subtotal. Historical snapshots are deliberately not rewritten by this change.

### P2 — Photo mapping and licensing (not implemented)

- [ ] Eliminate duplicated photo rules between `frontend/app.js` and `frontend-vendor/app.js`, or add automated parity checks if a shared module is incompatible with current static hosting.
- [ ] Add regression fixtures for similar dish names, Arabic names, and missing photos.
- [ ] Create an asset manifest keyed by exact filename with source URL, creator, license/version, attribution, and modification notes.
- [ ] Verify original source/license for each mapped asset; existing credit labels alone are not independent license verification.

### P2 — SEO (domain-dependent; intentionally left unchanged)

- [ ] Replace placeholder relative sitemap URLs with absolute canonical URLs.
- [ ] Include eligible public dish/cook pages and exclude private/hidden pages and vendor/admin workflows.
- [ ] Reference the sitemap from `robots.txt` once the canonical domain is known.
- [ ] Review Arabic title/description metadata and canonical behavior without changing the current language URL structure.
- **Blocked:** Production domain is not finalized. Do not invent a domain or generate canonical URLs until it is supplied. Keep the existing URL structure; do not introduce `/en/` or `/ar/` prefixes as part of this PR.

### P2 — Browser, accessibility, and operational checks (not implemented)

- [ ] Add browser tests for bilingual catalog, cart totals, checkout, cancellation, order status, and delivery updates.
- [ ] Add an automated accessibility scan for critical customer pages and keyboard navigation checks.
- [ ] Verify persistent upload storage, stable signing-key configuration, migration ordering, backups, and restore procedure through redacted read-only deployment metadata.
- [ ] Add aggregate metrics for search no-results, checkout funnel, refund reconciliation, delivery subsidy, and vendor settlement status when those data sources are available.

## Merge checklist

- [ ] Review code and schema compatibility, including existing databases.
- [ ] Confirm GitHub Actions passes, including all new tests.
- [ ] Review refund money-movement and delivery-state failure-path tests.
- [ ] Confirm no secrets, credentials, or personal customer data are added.
- [ ] Obtain explicit approval before merge or deployment.

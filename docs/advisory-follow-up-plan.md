# Remaining advisory work for PR #19

This checklist keeps the remaining advisory findings visible in the current review. Items marked **blocked** need a business rule or production-domain value before a safe implementation can be merged. No production data or credentials are required for this plan.

## Included in this PR
- [x] Expand smart-search matching to Arabic/English descriptions, ingredients, and allergen fields.
- [x] Add focused unit tests for normalized search text and missing optional translations.

## Follow-up implementation work

### P1 — Refund reconciliation
- [ ] Add a durable refund-operation model and migration (order/vendor-order reference, PaymentIntent, amount/currency, idempotency key, provider refund ID, state, timestamps).
- [ ] Make refund requests recoverable when the provider succeeds but local persistence fails.
- [ ] Reconcile provider-side refunds, including refunds created outside the application, before calculating additional refundable amounts.
- [ ] Test retry/idempotency, external refunds, partial multi-vendor refunds, and database failures.
- **Safety gate:** Do not deploy or change refund behavior until migration/backfill behavior and Stripe test-mode cases are reviewed.

### P1 — Delivery status and cost controls
- [ ] Represent an unknown actual delivery cost separately from a confirmed zero cost.
- [ ] Reject or explicitly gate transitions to `delivered` / `paid` when required cost or payment evidence is missing.
- [ ] Synchronize permitted delivery status transitions with the related order status and order event log in one transaction.
- [ ] Test failed/cancelled deliveries, status mismatch, cost corrections, and settlement reconciliation.
- [ ] Decide whether multi-vendor checkouts can share a courier run and how the shared cost is allocated.
- **Safety gate:** Preserve manual dispatch; do not imply a courier has been paid from an application status field alone.

### P1 — Commission policy
- [ ] Confirm the commission base: food subtotal, vendor-funded discounts, platform-funded discounts, loyalty points, tax, and customer delivery fees.
- [ ] Implement an explicit commissionable-amount helper and regression tests after policy approval.
- [ ] Preserve historical commission snapshots; do not silently recalculate past orders.
- **Blocked:** Business policy must be confirmed before changing the current calculation.

### P2 — Photo mapping and licensing
- [ ] Eliminate duplicated photo rules between `frontend/app.js` and `frontend-vendor/app.js`, or add automated parity checks if a shared module is not compatible with the current static hosting setup.
- [ ] Add regression fixtures for dishes with similar names, Arabic names, and missing photos.
- [ ] Create an asset manifest keyed by exact filename with source URL, creator, license/version, attribution text, and modification notes.
- [ ] Verify the original license/source for each mapped asset; existing credit labels alone are not independent license verification.

### P2 — SEO
- [ ] Replace the placeholder relative sitemap URLs with absolute canonical URLs.
- [ ] Include eligible public dish and cook pages; exclude private/hidden pages and vendor/admin workflows that should not be indexed.
- [ ] Reference the sitemap from `robots.txt`.
- [ ] Add Arabic title/description metadata and review canonical/hreflang behavior for the actual language URL strategy.
- **Blocked:** Confirm the production canonical domain and the site's English/Arabic URL strategy before generating canonical URLs.

### P2 — Browser, accessibility, and operational checks
- [ ] Add browser tests for bilingual catalog, cart totals, checkout, cancellation, order status, and delivery updates.
- [ ] Add an automated accessibility scan for critical customer pages and keyboard navigation checks.
- [ ] Verify persistent upload storage, stable signing-key configuration, migration ordering, backups, and restore procedure through redacted read-only deployment metadata.
- [ ] Add aggregate metrics for search no-results, checkout funnel, refund reconciliation, delivery subsidy, and vendor settlement status when those data sources are available.

## Merge checklist
- [ ] Review code and migration impact.
- [ ] Confirm GitHub Actions passes, including the new search tests.
- [ ] Review all P1 money-movement and delivery-state tests.
- [ ] Confirm no secrets, credentials, or personal customer data are added.
- [ ] Obtain explicit approval before merge or deployment.

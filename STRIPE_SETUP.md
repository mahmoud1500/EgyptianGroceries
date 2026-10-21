# Stripe Card Payments — Setup Guide

Your marketplace already has all the Stripe plumbing built in: when a
customer picks **Credit Card** at checkout, the site sends them to Stripe's
own secure payment page (or, on the mobile app, opens Stripe's payment
sheet). Orders are marked paid automatically by a webhook, and the card's
**brand + last 4 digits** (e.g. "Visa •••• 4242") are saved on the order so
you can see them in the admin panel.

**Card numbers never touch your server.** The customer types their card on
Stripe's hosted page (or in Stripe's in-app sheet). Your server never sees,
stores, or logs the card number, expiry date, or CVC. That is what keeps
you out of PCI-compliance scope — Stripe handles all of it. This guide
contains no secrets; your keys live only in environment variables on your
machine/server.

Until you do this setup, the Credit Card option is marked *coming soon* and
cannot be used to create an unpaid card order. Zelle, Venmo, and cash remain
available as recorded-only payment methods.

---

## Step 1 — Create a Stripe account

1. Go to <https://stripe.com> and sign up.
2. In the Stripe Dashboard, make sure **Test mode** is ON (top-right
   toggle) while you are testing. Test mode uses pretend money.

## Step 2 — Get your TEST keys

1. In the Dashboard (test mode), go to **Developers → API keys**.
2. Copy the **Secret key** — it starts with `sk_test_...`.
   (The Publishable key `pk_test_...` is not needed by this app's
   website flow; the backend does everything with the secret key.)
3. **Never** paste this key into chat, email, git, or any file in the
   project folder. It goes in an environment variable only (next step).

## Step 3 — Set the keys on your machine / server

On your Windows machine (PowerShell or Command Prompt), run:

```
setx STRIPE_SECRET_KEY "sk_test_..."
setx FRONTEND_URL "http://localhost:8000"
```

Then **close and reopen** your terminal / VS Code so the new variables are
picked up, and restart the server (`uvicorn app.main:app --reload`).

- `FRONTEND_URL` is the address customers use to reach the site. For local
  testing `http://localhost:8000` is fine. When the site is hosted, set it
  to the real address, e.g. `https://yoursite.com`.
- On a Linux host you can instead put the same variables in a `.env` file
  or your hosting panel's environment settings — same names.

To check it worked: open `http://localhost:8000/api/stripe/status` in your
browser. It should say `{"card_payments_enabled":true}`. (This endpoint
never reveals the key itself.)

## Step 4 — Register the webhook (marks orders paid)

The webhook is how Stripe tells your server "the payment went through" —
without it, customers pay but orders stay unpaid in the system.

1. In the Stripe Dashboard (test mode), go to
   **Developers → Webhooks → Add endpoint**.
2. Endpoint URL:

   ```
   https://<your-domain>/api/stripe/webhook
   ```

   Replace `<your-domain>` with your real hosted address. **Note:** Stripe
   cannot reach `localhost`, so the webhook only works once the site is
   hosted (or exposed through a tunnel such as Cloudflare Tunnel /
   `stripe listen` — see below). For pure local testing of the checkout
   redirect, the webhook is not required, but orders won't auto-mark paid.
3. Select these events:
   - `checkout.session.completed`
   - `payment_intent.succeeded`
4. After creating the endpoint, click **Reveal** on its **Signing secret**
   — it starts with `whsec_...`.
5. Set it the same way as the API key:

   ```
   setx STRIPE_WEBHOOK_SECRET "whsec_..."
   ```

   and restart the server.

### Local webhook testing (optional, with the Stripe CLI)

```
stripe login
stripe listen --forward-to localhost:8000/api/stripe/webhook
```

The CLI prints a `whsec_...` signing secret — use that one in
`STRIPE_WEBHOOK_SECRET` while testing locally.

## Step 5 — Test with the Stripe test card

1. Restart the server, open the site, and place an order choosing
   **Credit Card**.
2. You should land on Stripe's secure checkout page, and the card option
   on your site should now say **"Secure checkout via Stripe."**
3. Pay with the test card:
   - Number: `4242 4242 4242 4242`
   - Expiry: any future date (e.g. `12/34`)
   - CVC: any 3 digits (e.g. `123`)
   - ZIP: any value
4. After paying, you return to the site. Within a few seconds the webhook
   marks the order **paid**, and the order shows
   **Paid · Visa •••• 4242** on the customer's order page and in the admin
   order detail.
5. Try a declined card too: `4000 0000 0000 0002` — the payment fails and
   the customer gets the retry option, exactly like a real decline.

## Step 6 — Go live (when you're ready)

1. Finish Stripe's account activation (business details + bank account
   for payouts) in the Dashboard.
2. Turn **Test mode OFF** and go to **Developers → API keys** again.
3. Replace the environment variables with the live values:
   - `STRIPE_SECRET_KEY` → the `sk_live_...` key
   - Register the webhook endpoint **again** in live mode (same URL, same
     two events) and set `STRIPE_WEBHOOK_SECRET` to the live endpoint's
     `whsec_...` secret.
4. Restart the server. Real cards now charge for real.

## What is stored (and what is not)

| Stored on the order | Never stored anywhere |
|---|---|
| Card brand (`visa`, `mastercard`, …) | Full card number |
| Last 4 digits (`4242`) | Expiry date |
| Paid flag + Stripe session/intent reference | CVC / security code |

If card payments are ever misconfigured or Stripe is unreachable, the site
degrades gracefully: the Credit Card option is labelled as coming soon and
orders are recorded for manual payment, exactly as before this feature.

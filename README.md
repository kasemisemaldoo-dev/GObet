# GObet

GObet is a Python sports-market application with persistent accounts, password hashing, football and other sample markets, tickets, and administrator-managed accounts. Player sign-up and password changes are disabled. Only `zero5` can create accounts, reset player passwords, manage virtual balances, view every player's ticket, and inspect the transaction and activity ledgers. The admin has unlimited virtual credit authority; credits it issues do not debit an admin wallet.

## Run locally

1. Install Python 3.10 or newer.
2. Run `python -m pip install -r requirements.txt`.
3. Run `python app.py`.
4. Open `http://127.0.0.1:5000`.

The first server start creates the sole `zero5` admin account and prints a one-time password to the server log. Sign in with it, then choose **My account** to set a password of your choice (8 or more characters). To set the initial admin password yourself, define `GOBET_ADMIN_PASSWORD` before the account file is first created; it must contain at least 12 characters. Passwords are stored as hashes.

Accounts, tickets, virtual-credit transactions, and security/account activity entries live in `data/users.json`. Existing ticket histories are backfilled into the ledger during migration. This file is excluded from Git. The local account file is separate from any hosted server; publishing the source does not upload existing users or passwords. Back it up securely if you need to preserve local accounts.

## Deploy from GitHub

GitHub Pages only serves static files; it cannot run the Flask API or save account data, which is why sign-in fails when the project is published there. Deploy the full app as a Python web service instead:

1. Push the repository to GitHub without `data/users.json`.
2. In Render, create a **Blueprint** from the GitHub repository. The included `render.yaml` configures Gunicorn, HTTPS cookies, and a persistent disk for account data.
3. Wait for the service to deploy, then open its Render URL.
4. Read the first `Initial admin login` password in the Render service logs and sign in as `zero5`.
5. Use **Admin** to create player accounts and set their initial passwords. Players cannot self-register or change passwords.

The hosted service has its own account store. Existing local accounts are not copied to Render automatically. Keep `GOBET_SECRET_KEY` stable and do not publish it or the user file.

## Important

Accounts are persistent, but balances, credit adjustments, and wagers are virtual. The app does not provide cash deposits, payment processing, live odds, bet settlement, or withdrawals. Fixtures and prices are sample data. This code is not a licensed real-money betting service; removing these notices would not make it one. A cash-wagering service requires jurisdiction-specific licensing, legal review, identity/age verification, payment providers, security review, and live data/settlement systems.
# Orbit Lite (Termux-friendly)

Python standard-library-only messenger prototype. Features:
- Self-service registration (email, username, display name, password)
- Login by username or email + password + emailed 6-digit second-factor code
- Code expires after 5 minutes; max 5 tries; resend cooldown 45 seconds
- Search users by username/name/ID and direct messages
- Chat list, theme switch, settings for username/email
- Two-column workspace on phone and desktop (sidebar + conversation)

## Run

```bash
python main.py
```
Open `http://127.0.0.1:8000`.

No `pip install` is needed (stdlib only).


## Email setup for 2-step login

Login codes require SMTP credentials. Set the environment variables before starting the server. Example (replace with your provider settings):

```bash
export SMTP_HOST='smtp.example.com'
export SMTP_PORT='465'
export SMTP_USER='you@example.com'
export SMTP_PASSWORD='mail-provider-app-password'
export SMTP_FROM='you@example.com'
python main.py
```

For Gmail, use an App Password with 2-step verification enabled; do not put your normal account password in the code. For other providers, use their SMTP host and app-specific credential. **Without SMTP configuration, login will deliberately fail to send the code rather than silently skip 2FA.**

## Updating an existing Orbit database

The app upgrades the `users` table in place if the email column is missing. Keep a backup of `orbit.db` before updates. Do not share your database file.


## Notes

- This is a prototype; before public hosting, add HTTPS, CSRF protection, stronger request throttling, secure cookie settings for HTTPS, and persistent storage.
- The default cookie is `HttpOnly` and `SameSite=Lax`; use HTTPS in production.


## Media/profile features (this build)
- Avatar uploads: image only, maximum 3 MB.
- Chat attachments: images, videos, audio, PDF, TXT, ZIP and generic binary files, maximum 15 MB per file.
- Message forwarding: use the message button and enter the recipient account ID.
- Saved profiles are device-local usernames/display labels only; passwords are never stored. Switching a saved profile requires signing in again.
- Uploaded files are private: requires a login and access as uploader, conversation participant, or avatar owner.
- Files are stored in the local `uploads/` directory and database records in `orbit.db`.

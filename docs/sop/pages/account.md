---
page: /account
title: My account
routes: /account
mark: Change the password
---
Your own sign-in: change your password and turn two-step sign-in (a code from an authenticator app
after the password) on or off. Open it from your name at the top right, then **My account**. The
heading shows your name and the email you sign in with.

**Change my password**
- **Current password** (field): the password you use now.
- **New password** (field): at least 10 characters.
- **New password again** (field): the same new password.
- **Change the password**: checks the current password and the rules, then saves the new one. The
  page shows "Password changed: sign in again with the new one" and signs you out after a moment.
- What is refused: fewer than 10 characters; a common password (for example the company's name,
  "password", "welcome", the month and year); the same character repeated; a plain sequence
  ("12345678...", "abcdefgh...", "qwerty..."); a password containing your email name or a part of
  your name of 4 letters or more.
- After the change every session of yours ends, on every phone and computer. Sign in again
  everywhere with the new password. A lock from wrong passwords is lifted at the same time.

**Two-step sign-in**
- The state: **on** "since <date>: after your password, the code from your authenticator app", or
  **off** with "Add a code from an authenticator app to your sign-in." When your role must use it:
  "Your role needs it: you will set it up at your next sign-in."
- **Set it up** (when it is off): shows a QR code and the **Key** (the same secret as text, for
  typing in by hand).
  1. Open Google Authenticator or Microsoft Authenticator on your phone and add an account by
     scanning the QR code (or typing the key).
  2. Type the 6-digit code the app shows in **6-digit code**.
  3. Press **Turn it on**. The page shows "Two-step sign-in is on".
- From then on, every sign-in asks for the code after the password.
- **Turn it off** (only when your role does not require it): type a current code from the app in
  **code to turn it off** and press **Turn it off**. The page shows "Two-step sign-in is off".

**Sessions**
- The page has no list of your sessions. To end every session of yours (for example after you
  signed in on someone else's phone, or lost a phone), change your password: all sessions end.
- A session also ends by itself after a time without use, set by the company in Settings >
  Security: 12 hours on a phone and 8 hours on a computer by default. Then you sign in again.
- **Sign out** (under your name at the top right) ends the session on this device only.
- **Look** (under your name): **Dark** or **Light**. Your choice is kept for you on every device.

**Rules**
- Only you change your own password here. The office admin cannot see it; they can only send you a
  one-time link to set a new one (valid 7 days, works once).
- After 5 wrong passwords the sign-in is locked for 15 minutes. After the third lock in a row it
  stays locked until the office admin unlocks it (Users > Unlock). The login page shows the same
  "Invalid email or password" in every case.
- The company can require two-step sign-in for some roles (Settings > Security). For those roles it
  cannot be turned off here, and the setup is asked at the next sign-in.
- The two-step setup must be finished within 10 minutes of pressing **Set it up**.

**What happens next**
- After a password change: sign in again on every device you use.
- After two-step is on: keep the phone with the authenticator app. A lost phone means the office
  admin must reset your two-step sign-in (Users), then you set it up again.

**Hands off**
- Receives: your first password link and any unlock or two-step reset from the office admin.
- Passes on: nothing.

**When it goes wrong**
- "The two new passwords are not the same": type the new password the same way in both fields.
- "The current password is not right": type the password you use now. If you forgot it, ask the
  office admin for a set-password link.
- "The password needs at least 10 characters", "That password is too common: choose another",
  "The password repeats the same characters: choose another", "The password is a plain sequence:
  choose another", "The password must not contain your email", "The password must not contain your
  name": choose a different new password.
- "Start again: the setup took too long" or "Start again": reload the page and press **Set it up**
  again; remove the old entry from the authenticator app and scan the new QR code.
- "That code is not right: try the newest one": wait for the next code in the app and type it
  quickly. If it keeps failing, check that the phone's time is set automatically.
- "Two-step login is required for your role (Settings > Security)": your role must keep it on.
- "That code is not right" (turning it off): type the code the app shows now.
- "Your password was changed: sign in again": the password was changed on another device (or by a
  set-password link). Sign in with the new password.
- "Session expired": you were away longer than the company's limit. Sign in again.

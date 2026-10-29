---
page: _first-login
title: Your first login
routes: /login, /set-password/:token
---
How to get into the app the first time, and what to do when signing in goes wrong.

**1. Open your link**
- The office admin (or the super admin) sends you a one-time link by WhatsApp, SMS or email. The app itself sends no email: the link always comes from a person.
- The link works once, for 7 days. Asking for a new one stops the old one.
- It opens **Set your password**, with your name and email under it.

**2. Set your password**
- **New password (at least 10 characters, not a common one)**: type your password.
- The rules: at least 10 characters; not a common password (such as "password123" or "welcome@123"); not your name or the first part of your email; not one character repeated; not a plain sequence such as "1234567890" or "qwertyuiop".
- While you type, a warning under the box tells you what is wrong ("That password is too common: choose another" ...). **Set the password** stays grey until the warning is gone.
- **Again**: the same password again.
- **Set the password**: saves it and opens the login page. Your account is now active.

**3. Sign in**
- The login page: **Sign in**, with **Email** and **Password**.
- **Sign in**: checks them. You land on your first page (My work), or on the portal for a client contact.
- There is no "forgot password" on the login page. Ask the office admin for a new link or a password reset.
- On the training company, a "TRAINING" line at the top says the data is for practice only.

**4. Two-step sign-in**
- When the director or an admin switches it on in Administration > **Security**, the roles ticked there must use two-step sign-in. Directors, office admins and accounts are the roles ticked from the start. Everyone else may turn it on for themselves in **My account**.
- Before your first sign-in, install Google Authenticator or Microsoft Authenticator on your phone.
- The first time, after your password, the page says "Set up two-step sign-in. Your role needs it: scan this code with an authenticator app (Google or Microsoft Authenticator), then type the 6-digit code it shows."
- Scan the QR code with the app, or type the key shown under it ("Or type this key into the app").
- **Code**: type the 6-digit code the app shows now. **Sign in** finishes. Two-step sign-in is then on.
- From then on, every sign-in asks "Type the 6-digit code from your authenticator app." after your password.
- **Start again**: back to email and password.
- You have 5 minutes after the password to type the code.
- To set it up without being asked: **My account** > **Two-step sign-in** > **Set it up**, scan the code, type the **6-digit code**, **Turn it on**. To turn it off (only when your role does not need it): type a code in **code to turn it off**, then **Turn it off**.
- Lost or changed phone: ask the office admin to press **Reset two-step** on you in Users. If your role needs it, you set it up again at your next sign-in.

**5. Put the app on your phone's home screen**
- The app is a web page: there is nothing to install from a store, and the app does not offer an install button.
- Android (Chrome): open the app's address, sign in, tap the ⋮ menu, then **Add to Home screen**.
- iPhone (Safari): open the address, tap the Share button, then **Add to Home Screen**.
- The icon opens the app in the browser. You stay signed in until the session ends (below).

**6. Sessions and locks**
- You are signed out after a time without using the app: 12 hours on a phone and 8 hours on a computer, unless the director or an admin changed it in Administration > **Security**. Sign in again.
- Changing your password (in **My account**), or the office admin resetting it, signs you out on every device.
- When the office admin deactivates your account, you are signed out at once.
- 5 wrong passwords (or wrong two-step codes) in a row lock your sign-in for 15 minutes. After the third lock in a row, it stays locked until the office admin presses **Unlock**.
- While locked, the page says only "Invalid email or password", even for the right password. Wait 15 minutes, or call the office admin.

**When it goes wrong**
- "This link was used already or has expired: ask the office admin for a new one": ask for a new link.
- "The two passwords are not the same": type the same password in both boxes.
- "The password must not contain your name" / "The password must not contain your email": shown after **Set the password**; choose a password without them.
- "Invalid email or password": the email or password is wrong, your account is locked, not set up yet, or deactivated. The app does not say which. Check the email, wait 15 minutes, then ask the office admin.
- "Could not reach the server": no internet, or the server is down. Try again in a minute.
- "That code is not right: check the time on your phone and try the newest code": type the newest code. If it keeps failing, set your phone's time to automatic.
- "The sign-in took too long: start again" / "Start the sign-in again": press **Start again** and sign in again.
- Sent back to the login page in the middle of work: the session ended (time without use, a password change, or the account deactivated). Sign in again.
- "No access. You do not have permission to open this page.": the page is not part of your role. Use the menu.

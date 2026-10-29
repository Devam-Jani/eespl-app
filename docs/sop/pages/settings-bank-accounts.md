---
page: /settings/bank-accounts
title: Bank accounts
routes: /settings/bank-accounts
mark: Add account
---
The company's own bank accounts. The **default** account is the one printed on bills. Accounts
may read this list; only the company settings right adds or changes an account. Every change is
written to the audit log (only the last 4 digits of the account number are kept there).

**On the page**
- The table: **Account name**, **Account number**, **IFSC**, **Bank / branch**, and a **default** badge. The default comes first.
- **⤓ Export Excel**: downloads the accounts (name, number, IFSC, bank, branch, default) as an Excel file.
- **Add account**: opens the **Add bank account** form. {perm: settings.company}
- **Edit** (on a row): opens **Edit bank account**. {perm: settings.company}

**The form (Add bank account / Edit bank account)** {perm: settings.company}
- **Account name**: the name on the account. {perm: settings.company}
- **Account number**: 6 to 18 digits; spaces and dashes are removed. Only typed when adding. {perm: settings.company}
- **IFSC**: 11 characters, like HDFC0001234. Only typed when adding. {perm: settings.company}
- **Bank**, **Branch**: optional. {perm: settings.company}
- **Default account (printed on bills)**: tick it to make this the default; the old default loses its tick. {perm: settings.company}
- **Save**: saves and closes the form. {perm: settings.company}
- **Cancel**: closes without saving. {perm: settings.company}
- **Delete**: shown when editing. Asks "Delete the account ending <last 4 digits>?" and removes it. {perm: settings.company}

**Rules**
- The first account added becomes the default by itself.
- The account number and IFSC cannot be changed once saved. For a new number, add a new account and delete the old one. {perm: settings.company}

**What happens next**
- Bills printed from now on show the default account.

**Hands off**
- Receives: the bank details from accounts.
- Passes on: the account printed on billing's bills.

**When it goes wrong**
- "Account number must be 6 to 18 digits": type only the digits.
- "IFSC must look like HDFC0001234 (4 letters, 0, then 6 letters/digits)": check the IFSC on the cheque leaf.

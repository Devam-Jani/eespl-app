---
page: /petty-cash
title: Petty cash
routes: /petty-cash
mark: + Expense
---
Petty cash is one account per person. Accounts give an advance, the person records each expense
from it with the bill photo, and accounts approve or reject each expense and take back the cash left
over. An approved expense is charged to its site's budget.

**On the page**
- **Give advance**: opens **Petty cash advance**. {perm: expense.approve}
  - **To** (required): the person. The first advance opens their account. {perm: expense.approve}
  - **Amount (₹)** (required). {perm: expense.approve}
  - **Mode**: cash, upi or neft. For upi and neft, **From bank**: the company bank account. {perm: expense.approve}
  - **Date** (today by default; no future date) and **Remark**. {perm: expense.approve}
  - **Give**: records the advance. It counts in the balance at once. {perm: expense.approve}
- **+ Expense**: opens the **Expense** form. Shown once you have an account. {perm: expense.create}
  - **Amount (₹)** (required). {perm: expense.create}
  - **Category** (required): tap one (the categories decide the budget head). **Submit** stays grey until a category is picked. {perm: expense.create}
  - **Site**: the site the expense is for, or "— office / none —". {perm: expense.create}
  - **Paid to**, **Date** (today by default; no future date), **Remark**. {perm: expense.create}
  - **Photo of the bill (required above the limit)**: opens the camera, or pick a photo or PDF. {perm: expense.create}
  - **Submit**: records the expense as submitted (waiting for approval). **Cancel** closes the form. {perm: expense.create}
- **My balance**: your balance now, and "₹n waiting for approval" when expenses wait. {perm: expense.create}
- Your entries, newest first: date, what (category and site, or "Advance given" / "Cash
  returned"), paid to and remark, the amount (+ for advances, - for spending), a **submitted** or
  **rejected** badge (with "Why: <reason>" under it), and **bill** to open the photo.
- "No petty cash account yet: it opens with the first advance." when you have none.
- **Accounts**: everyone's accounts with **Person**, **Advances**, **Spent**, **Returned**, **Waiting** and **Balance**. Press a row to open the person's account. {perm: expense.approve}
- In a person's account ("Petty cash: <name>"): "Balance ₹n · waiting ₹n" and the entries. {perm: expense.approve}
  - **Approve**: approves a submitted expense. It then counts in the balance and in the site's cost. {perm: expense.approve}
  - **Reject**: asks "Why is it rejected?". With a reason the expense is marked rejected and does not count. Cancel or an empty reason does nothing. {perm: expense.approve}
  - **Record cash returned**: asks "Cash returned by <name> (balance ₹n):" and records the cash handed back. {perm: expense.approve}

**Rules**
- Balance = advances - approved expenses - cash returned. Expenses waiting for approval are not
  taken off yet.
- An expense above the photo limit (₹500 by default, set by accounts) needs the bill photo.
- You record expenses from your own account only.
- Only submitted expenses can be approved or rejected; a decision is final.
- Cash returned cannot be more than the balance in hand.
- A balance below zero raises the **Petty cash balance negative** alert for accounts.

**What happens next**
- Your expense waits in accounts' **Waiting** column until they approve or reject it. There is no
  to-do or notification for it; tell accounts when you have bills waiting.
- An approved expense is charged to the site's budget head for its category.

**Hands off**
- Receives: the advance from accounts. {perm: expense.create}
- Passes on: your expenses with their bills to accounts for approval. {perm: expense.create}
- Receives: the expenses of site staff to approve; passes on: the cost to the site budgets. {perm: expense.approve}

**When it goes wrong**
- "No petty cash account yet: an advance opens it": ask accounts for an advance first.
- "A bill photo is required above ₹n": take the photo of the bill and submit again.
- "Category not found" / "Site not found": reload the page and pick again.
- "<number> is approved" / "<number> is rejected": the expense was already decided. Reload.
- "Give the reason for rejecting": type a reason in the box.
- "More than the balance in hand": check the amount handed back against the balance.
- "User not found" / "Bank account not found": pick the person or the bank again.
- "Missing permission: expense.create": your role does not hold petty cash.

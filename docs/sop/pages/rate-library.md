---
page: /rate-library
title: Rate library
routes: /rate-library
mark: ⤓ Export results
---
The **Rate library** holds the BOQ items of our past files with the rates they were quoted at: the latest, the lowest, the median and the highest, and in how many BOQs each item appears. Search it to price a new BOQ line from what we quoted before.

**On the page**
- **Search past BOQ items** (box): searches as you type. Empty: the most quoted items.
- **Unit** (list): "Any" or one unit.
- **Include flagged** (tick box): also show working or margin rows, rates below ₹1 and items hidden by hand.
- **Include competitor rates** (tick box): also show other contractors' rates taken from comparative sheets.
- **⤓ Export results**: downloads the results with the same search, unit and tick boxes as an Excel file.
- The line above the table: how many results, for which words, and the time taken. "showing the closest matches" when the list was cut to the best matches.
- The table: **Description**, **Unit** (point at it to see the unit as written), **Latest** (in bold when it is the suggested rate), **Min**, **Median**, **Max**, the flags, **BOQs**, **Latest channel**.
- The flags: **Other bidder** (red: another contractor's rate, not ours), **Hidden: <reason>** (grey), or a check note (yellow).
- **Show more**: loads the next 25 results.
- Click a row to open the **Library item** window.

**The Library item window**
- The description, the unit (and as written), the suggested or latest rate, the min–max and median, and in how many BOQs.
- "Figures recomputed from EESPL's own lines below (other bidders' and flagged lines left out)." when the figures were worked out again from the lines.
- **Source lines** (table): **Client**, **File** (with the sheet and row), **Item**, **Unit**, **Qty**, **Rate** and the flags. "other file" marks a file not priced by us; "merged" marks a line that came from a merged item.
- **Hide from search**: asks "Why should this item be hidden from search?" and hides the item with that reason. Cancel or an empty reason does nothing. {perm: library.edit}
- **Show in search again**: shown instead on a hidden item; puts it back in search. {perm: library.edit}
- **Change unit** (list): sets the item's unit at once. The unit as written in the files is kept. {perm: library.edit}
- **Merge into…**: opens a search of other items. Click the item to keep; confirm "Merge this item into ...? You can unmerge later." This item's lines then count towards that item, this item leaves search, and the window opens the kept item. Nothing is deleted. {perm: library.edit}
- **Unmerge**: on a merged item, or on a row of "Merged into this item:", splits the item off again. {perm: library.edit}
- "Merged into <item> ... It no longer appears in search.": click the item's name to open the one it was merged into.

**Rules**
- Hiding, unhiding, a changed unit and merges survive a re-import of the BOQ files.
- Competitor rates and flagged rows are left out of the figures unless you tick them in.
- Every change is written to the audit log.

**What happens next**
- The median rates feed the **Pricing position** tab of **Strategy**.

**Hands off**
- Receives: the lines read from our past BOQ files.
- Passes on: past rates to the estimator for new tenders and quotations.

**When it goes wrong**
- "Nothing matches. Try fewer or different words.": use fewer words or a broader term.
- "Give a reason for hiding this item": type a reason when hiding.
- "Unknown unit: <unit>": choose another unit.
- "An item cannot be merged into itself", "This item is already merged into another item", "The target item is itself merged; merge into the item it points to": pick another item to keep.
- "This item is not merged": it was unmerged already. Reload.

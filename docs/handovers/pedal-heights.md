# Handover: research pedal heights (web research only, no repo edits)

Goal: for each pedal in your list, find its published HEIGHT in mm (how tall it stands on the board: base to the top of
the tallest part, usually knobs or footswitch). The owner will use it later to estimate footswitch reach and where
toppers help. Do NOT edit any file in the repo; return the data in your final message.

## Rules (project conventions)
- Never invent or estimate a value. No source = `null`.
- Source priority: maker (product page, manual, spec sheet) > retailer (Thomann, Sweetwater, Andertons, Reverb listing)
  > forum / review. Prefer the maker. When sources disagree, take the maker's figure and mention the others.
- Convert inches to mm (x 25.4, one decimal). Most specs give W x D x H; make sure you take the HEIGHT (the smallest
  figure for a normal stompbox is usually the height, but check the label). Say what the figure includes when the source
  says so: `overall` (incl. knobs / footswitch), `enclosure` (body only), or `unspecified`.
- Mind the exact version (e.g. Mk2, V3, V4, Deluxe, Mini): a figure for another version is not the pedal's figure; you
  may note it but leave `height_mm` null unless the enclosure is the same and a source says so.
- Retailer pages may block bots (Thomann answers 429); try another source rather than retrying.

## Output (final message): one JSON object per pedal, one per line
`{"id": "<id>", "height_mm": <number or null>, "measure": "overall|enclosure|unspecified|null",
"confidence": "maker|retailer|forum|null", "source": "<site name>", "url": "<url>", "notes": "<short: raw figure as
published, version caveats, conflicting figures>"}`
Then a short summary: how many found, which are null and why.

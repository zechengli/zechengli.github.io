# DejaRAN reorg notes (restructured draft)

Files: `dejaran.tex`, `refs.bib`. Not compiled (no LaTeX toolchain on the lab machine).

## What changed vs. the original

1. **Title is now a claim, not a question.** "DejaRAN: A Bug Is a History, Not a Version" (was "What the History... Says About Its Bugs").

2. **Abstract and Intro lead with the thesis.** New one-sentence position, stated verbatim in Intro under **Our position**: a bug is a property of history, and a bug finder should emit a *switch*, not a report. Specula compressed to one sentence in the opening. The five findings F1–F5 stay as a tight list.

3. **New "why RAN" paragraph** in Intro: main changes daily but releases run for months (POWDER/COSMOS); bugs are timing bugs so a model checker is the right lens; a one-layer bug surfaces only through MAC+DU. This answers "why not FSE".

4. **Structure follows the counter-plan (6 pages):**
   - Intro (thesis-first)
   - Background: RLC AM, keeps **Fig 2** (stack) verbatim; foregrounds only H, D, C, BS; keeps full bug **Table 1**.
   - How we pick versions: keeps **Fig 1** (grid) verbatim (caption simplified; mask letters flagged for a possible separate panel). TLA+ model reduced to essentially one sentence. **ABSC demoted** from its own full figure to a method paragraph (13/15 kept in prose). Original **Fig 3 (switch_H listing) dropped.**
   - Experiments (the body, ~3pg): H (incl. cross-version F2 + OTA stub + F4 deleted-test sidebar), F1 (D+C, with release table + the DONE ZMQ C-fix-pair live-link numbers), F5 (MAC hides C, with the DONE live-link numbers), F3, F4.
   - Lessons + call to action: ship the setting / testbeds read the setting / deleting a test deletes knowledge, emit a switch.
   - Related work (trimmed) + Limits.

5. **New cost table (Table `tab:cost`):** Specula ~21h/~$740 per version vs DejaRAN 287-version scan ~5s + 460 MC runs / 447s.

6. **F5 no longer says "we have not tested D on a live link."** The DONE experiments are used with real numbers:
   - L2-D (MAC default, 23.10.1 + 24.04, 5 runs each): MAC RLF first in all 10 at 0.33–0.87s; RLC max-retx on 24.04 at 0.729–0.744s but after MAC.
   - L2-P (C-fix pair full stack, 5 runs each): parent 84cb8e6afd no max-retx 5/5; fix 316da8f08c max-retx 0.733–0.745s 5/5, UE released.
   These come from `l2/L2DP_RESULTS.md` and `l2/L2C_RESULTS.md`.

## OPEN TODOS (also in a comment block at the top of dejaran.tex)

- **[TODO-OTA]** H over-the-air on B210 + patched srsUE: one crafted STATUS PDU to a real gNB, cross-version 25.10 / 26.04 / main. `srsue_mute` is patched and `l2rf/` scripts exist, but there is **no RF result directory yet**. All OTA numbers in the draft are placeholders — do not invent them. If OTA doesn't land, delete the OTA paragraph; the real-code unit results + ZMQ live-link results stand alone.
- **[TODO-UP]** Upstream status of D, BS, RC, R (issues/MRs filed? dev response?). Only H (#801 → 2b9caf2bc) is confirmed closed. This strengthens "developers are the oracle" and adds real-world impact.
- **[TODO-FIG1]** Simplify Fig 1: consider splitting the pairwise-mask letters (C/Z) out of the main grid.
- **[TODO-N]** Snapshot count: prose says 287; the rerun on this machine shows 288 (dev advanced one commit, and H is now closed on main by 2b9caf2bc). Decide whether to keep the "before H was closed" snapshot framing or update to the post-fix state.
- **[TODO] F5 / D live-link**: the C and P full-stack runs are analyzed; state the D-isolating full-stack UE-visible outcome in the same form once analyzed (placeholder sentence is in the F5 subsection).
- **refs.bib**: entries marked `% CHECK` (ocudu, srsranproject, cheng2026specula, powder2026ocudu, cosmos2026ocudu, ts38322 version) need real venue/year/URL from the Mac's refs.bib.

## Not touched / preserved
- Fig 1 grid tikz and Fig 2 stack tikz copied verbatim from the original.
- Table 1 (bugs) preserved (compacted into a resizebox).
- Release table (Table `tab:release`) preserved verbatim.
- All real commit hashes and numbers preserved; prose hash density cut to ~1 per paragraph, the rest live in the tables.

---
type: comment
at: "2026-08-20T03:40:00Z"
by: "claude"
event: "note"
---

OPEN QUESTIONS FOR SEANWY (carried from CKM-41, plus what this build decided provisionally):
1. SIGNATURE SOURCE (CKM-41 q2): implemented as local per-profile signature_html in profiles.toml, because the roaming Outlook signature would need MailboxSettings.Read — a scope this app deliberately never requests, and asking for it would have broken the "no new consent" condition A was chosen under. If you want the roaming one, that is a new scope decision, not a code change. Nothing is configured yet: your signature still has to be pasted into ~/.config/ckm365/profiles.toml once (off-repo, PUBLIC repo here). Want that done for you next session?
2. TOOL-COUNT BUDGET (CKM-41 q5): the five went into the EXISTING mail preset, so a --preset mail session grows from 24 to 28 tools with --write --enable-send. Say the word if you want them behind a separate preset instead.
3. POLICY (CKM-41 q4): "agents do not hand-roll Graph for mail WRITES" was NOT written into CLAUDE.md — that is a boundary change and it is yours to make. docs/graph-direct.md now leads with the check-for-a-tool table, which is the soft version of the same thing.
4. CKM-41 q1 (tenant-wide transcript switch) and q3 (fourth identity / allow_send) are untouched and still open on CKM-41.
5. Option C (CKM-31, publisher verification) is still not started. It is the only unbounded external clock on the board — worth 10 minutes when you are off the road.

---
type: comment
at: "2026-07-30T23:17:45Z"
by: "claude"
event: "moved"
---

DONE — live-verified end to end on the chosen tenant, fully scripted run. seanwy ran create-exo-automation-app.sh --yes (automation app, cert PFX, Exchange.ManageAsApp consent grant-verified, exchange-admin directory role verified); everything after was unattended: app-only EXO connect OK first try; create-test-mailbox.ps1 provisioned tst.apponly; setup-app-rbac.ps1 -Apply created SP registration + ckm365-app-scope + both Application role assignments, Test-ServicePrincipalAuthorization InScope True (scoped mailbox) / False (operator mailbox); Graph-app cert generated + uploaded; an app-only profile added (allow_send=false). VERIFIED (ClearKan asks 5.1/5.2): doctor OK; live-smoke app-only read OK and deny probe 403 ErrorAccessDenied on out-of-scope mailbox (the NEGATIVE test, at the Graph layer); full live suite 5/5 app-only; delta/watch app-only — bootstrap token, delegated profile sent a real message into the scoped mailbox, app-only wait_for_message caught it via token round-trip (matched 1, no behavioral difference vs delegated). KEY RESULT: RBAC-only is sufficient — ZERO Graph application permissions consented; add-app-permissions.sh not needed (kept in reserve). Runbook + usage-modes updated to verified status. Per-tenant repetition for the second tenant remains open (new issue if/when needed).

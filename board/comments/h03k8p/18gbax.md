---
type: comment
resource: oif:ckm/h03k8p/18gbax
at: '2026-11-10T07:40:01+00:00'
by: claude
---

Merged and released in v2.14.0. Reviewed: confine resolves symlinks before every check, the state, profiles and hidden-path denials apply whatever the root, and add_attachment uses attach_root(). The two collection-time probe fixes in the migrate tests are right. Checked offline against this machine's real config with no roots set: the token cache, profiles.toml and ~/.ssh are refused, a repo file is refused as outside the default root, and the default root works.

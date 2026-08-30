# ckm365 environment — SOURCE this file; do not copy it to `.env`.
#
# ckm365 reads os.environ directly. Nothing in the package parses a dotenv
# file (core deps are exactly httpx + msal), so a filled-in `.env` would be
# read by nobody and the profile would keep reporting a missing credential.
#
#   cp env.example.sh ~/.config/ckm365/env      # then edit
#   chmod 600 ~/.config/ckm365/env
#   echo '. "$HOME/.config/ckm365/env"' >> ~/.bashrc
#
# That covers the CLI. The MCP server is a separate process and does NOT
# inherit your shell rc unless Claude Code was itself started from a shell
# that sourced it — pass the same vars to `claude mcp add` with `-e`
# (see README "Setup" and docs/app-only-setup.md §2).
#
# No values committed, ever.

# Optional: path to profiles.toml (default: ~/.config/ckm365/profiles.toml)
#export CKM365_PROFILES=

# Per-profile app-only (client_credential) secrets. Profile name upper-cased,
# dashes -> underscores. Prefer the certificate pair over a client secret.
#export CKM365_TENANT_A_CLIENT_SECRET=
#export CKM365_TENANT_A_CLIENT_CERT_PATH=
#export CKM365_TENANT_A_CLIENT_CERT_THUMBPRINT=

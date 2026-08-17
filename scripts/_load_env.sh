#!/usr/bin/env bash
# ============================================================
# scripts/_load_env.sh — shared env loader for campaign scripts
#
# Source this from the top of any campaign script:
#       source "$(dirname "$0")/_load_env.sh"
#
# It loads, in order:
#   1) .env.local                (if present)   — picks up LLAMA_USER/PASS,
#                                                  REQUESTS_CA_BUNDLE, etc.
#   2) key.txt                   (if present and GPT4IFX_API_KEY unset)
#                                                — sets GPT4IFX_API_KEY
#   3) Defaults: GPT4IFX_BASE_URL = https://<your-llm-endpoint>
#                THESIS_LLM_ENABLED = 1
#
# Then it validates that AT LEAST ONE auth method is present
# (matches the logic in `python -m src.cli doctor`):
#
#   GPT4IFX_API_KEY                                        — bearer token
#   GPT4IFX_CLIENT_ID  + GPT4IFX_CLIENT_SECRET             — OAuth2 client_credentials
#   LLAMA_USER         + LLAMA_PASSWORD                    — basic -> token exchange
#
# On failure, prints clear hint and exits 1.
# ============================================================

# Locate repo root (one level up from this script)
_LE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 1) source .env.local if present
if [[ -f "$_LE_ROOT/.env.local" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$_LE_ROOT/.env.local"
    set +a
fi

# 2) fall back to key.txt for bearer token -- BUT only if no other
#    method is available. Bearer tokens expire after ~24h; basic
#    auth auto-exchanges for a fresh token every call. Prefer basic
#    if it's already set in .env.local.
_have_basic_pre=0
[[ -n "${LLAMA_USER:-}" && -n "${LLAMA_PASSWORD:-}" ]] && _have_basic_pre=1
_have_oauth_pre=0
[[ -n "${GPT4IFX_CLIENT_ID:-}" && -n "${GPT4IFX_CLIENT_SECRET:-}" ]] && _have_oauth_pre=1

if [[ -z "${GPT4IFX_API_KEY:-}" && -s "$_LE_ROOT/key.txt" \
      && $_have_basic_pre -eq 0 && $_have_oauth_pre -eq 0 ]]; then
    GPT4IFX_API_KEY="$(tr -d '\r\n' < "$_LE_ROOT/key.txt")"
    export GPT4IFX_API_KEY
fi
unset _have_basic_pre _have_oauth_pre

# 3) defaults
: "${GPT4IFX_BASE_URL:=https://<your-llm-endpoint>}"
: "${THESIS_LLM_ENABLED:=1}"
export GPT4IFX_BASE_URL THESIS_LLM_ENABLED

# 3a) Auto-detect CA bundle.
# The HTTPX client used by RAG/Indexer needs a CA file path that EXISTS,
# otherwise it raises SSLError that is silently swallowed and the basic
# auth path appears to "fail". Order of preference:
#   - GPT4IFX_CA_BUNDLE        (explicit, wins)
#   - <repo>/ca-bundle.crt     (laptop, gitignored)
#   - /etc/ssl/certs/ca-certificates.crt  (Ubuntu system bundle — has the
#                                          IFX certs after the WSL guide)
if [[ -z "${GPT4IFX_CA_BUNDLE:-}" ]]; then
    if [[ -f "$_LE_ROOT/ca-bundle.crt" ]]; then
        export GPT4IFX_CA_BUNDLE="$_LE_ROOT/ca-bundle.crt"
    elif [[ -f /etc/ssl/certs/ca-certificates.crt ]]; then
        export GPT4IFX_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
    fi
fi

# 4) validate at least one auth method (mirror cmd_doctor logic)
_have_bearer=0;   [[ -n "${GPT4IFX_API_KEY:-}" ]] && _have_bearer=1
_have_oauth=0;    [[ -n "${GPT4IFX_CLIENT_ID:-}" && -n "${GPT4IFX_CLIENT_SECRET:-}" ]] && _have_oauth=1
_have_basic=0;    [[ -n "${LLAMA_USER:-}"        && -n "${LLAMA_PASSWORD:-}"        ]] && _have_basic=1

if (( _have_bearer + _have_oauth + _have_basic == 0 )); then
    echo "[!] No GPT4IFX auth method found in this shell."
    echo "    Provide ONE of the following:"
    echo "      A) export GPT4IFX_API_KEY=\"\$(cat key.txt)\""
    echo "         (this script will auto-load key.txt if you put your token there)"
    echo "      B) export GPT4IFX_CLIENT_ID=... GPT4IFX_CLIENT_SECRET=..."
    echo "      C) export LLAMA_USER='DOMAIN\\\\user' LLAMA_PASSWORD='...'"
    echo "         (or uncomment these lines in $_LE_ROOT/.env.local)"
    echo
    echo "    Quick test:  python -m src.cli doctor --skip-auth-check"
    exit 1
fi

# Report what we have (no secrets printed)
_auth_methods=()
(( _have_bearer )) && _auth_methods+=("bearer(GPT4IFX_API_KEY)")
(( _have_oauth  )) && _auth_methods+=("oauth2(client_credentials)")
(( _have_basic  )) && _auth_methods+=("basic(LLAMA_USER+LLAMA_PASSWORD)")
printf "[i] auth: %s\n[i] base: %s\n[i] ca:   %s\n" \
    "$(IFS=,; echo "${_auth_methods[*]}")" \
    "$GPT4IFX_BASE_URL" \
    "${GPT4IFX_CA_BUNDLE:-(none — TLS verification disabled)}"

unset _LE_ROOT _have_bearer _have_oauth _have_basic _auth_methods

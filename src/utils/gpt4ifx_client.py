"""
GPT4IFX Client Wrapper
Handles authentication, retries, model switching for Infineon's GPT4IFX platform
"""

import os
import time
from typing import Optional, List, Dict, Any

import httpx
from openai import OpenAI
from openai import OpenAIError


def _mask_secret(s: Optional[str]) -> str:
    if not s:
        return "<empty>"
    s = str(s)
    if len(s) <= 8:
        return "<redacted>"
    return f"{s[:4]}...{s[-4:]}"


class TokenProvider:
    """Fetches and caches a GPT4IFX API token.

    Priority order:
    1) **Explicit bearer token** via `GPT4IFX_API_KEY` env var or `api_key` parameter.
       - This is the legacy/manual flow (developer token copied from docs portal).

    2) **Service account** via OAuth2 client-credentials (recommended for automation).
       - Env vars:
         - `GPT4IFX_TOKEN_URL` (optional; defaults to `{base_url}/auth/token`)
         - `GPT4IFX_CLIENT_ID`
         - `GPT4IFX_CLIENT_SECRET`
         - `GPT4IFX_SCOPE` (optional)
       - This tool will POST `grant_type=client_credentials` and read `access_token`.

    3) **Legacy basic-auth** token fetch using `LLAMA_USER` / `LLAMA_PASSWORD`.
       - This exists for backward compatibility and should be phased out.

    TLS / CA:
    - Set `GPT4IFX_CA_BUNDLE` to a CA path to enable TLS verification.
    - If not set, verification defaults to False to mimic the original doc snippet.

    IMPORTANT:
    - This class must not print secrets.
    """

    def __init__(self, base_url: str, ca_bundle_path: Optional[str], timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.ca_bundle_path = ca_bundle_path
        self.timeout = timeout
        self._cached_token: Optional[str] = None
        self._cached_at: float = 0.0

    def _token_endpoint(self) -> str:
        # Can be overridden for deployments where token URL differs from base_url.
        override = os.getenv("GPT4IFX_TOKEN_URL")
        if override:
            return override
        return f"{self.base_url}/auth/token"

    def _verify_setting(self):
        # Prefer explicit CA bundle if present; otherwise default to False to mimic doc snippet.
        env_ca = os.getenv("GPT4IFX_CA_BUNDLE")
        ca = env_ca or self.ca_bundle_path
        if ca:
            return ca
        return False

    def _fetch_permanent_token(self, user: str, password: str) -> Optional[str]:
        """LEGACY: fetch token using basic auth.

        This path is kept for backward compatibility.
        Prefer service-account client-credentials instead.
        """
        verify = self._verify_setting()
        url = self._token_endpoint()
        headers = {"Content-Type": "application/json"}

        with httpx.Client(verify=verify, timeout=self.timeout) as client:
            resp = client.get(url, headers=headers, auth=(user, password))

        if resp.status_code != 200:
            return None

        token = resp.text.strip().strip('"')
        return token or None

    def _fetch_service_account_token(self, client_id: str, client_secret: str, scope: Optional[str]) -> Optional[str]:
        """Fetch OAuth2 access token via client-credentials.

        Expected response:
        - JSON with `access_token` (preferred)
        - or plain text token (fallback)
        """
        verify = self._verify_setting()
        url = self._token_endpoint()

        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        if scope:
            data["scope"] = scope

        with httpx.Client(verify=verify, timeout=self.timeout) as client:
            resp = client.post(url, data=data)

        if resp.status_code != 200:
            return None

        # Most OAuth2 servers return JSON.
        try:
            js = resp.json()
            tok = js.get("access_token") or js.get("token")
            if tok:
                return str(tok).strip()
        except Exception:
            pass

        # Fallback: plain token
        tok = resp.text.strip().strip('"')
        return tok or None

    def get_token(self, api_key: Optional[str] = None) -> str:
        # Cached token (10 minutes) to avoid frequent token endpoint calls.
        if self._cached_token and (time.time() - self._cached_at) < 600:
            return self._cached_token

        # 1) Explicit bearer token (legacy/manual flow)
        token = api_key or os.getenv("GPT4IFX_API_KEY")
        if token:
            return token

        # 2) Service account client-credentials (recommended)
        client_id = os.getenv("GPT4IFX_CLIENT_ID")
        client_secret = os.getenv("GPT4IFX_CLIENT_SECRET")
        scope = os.getenv("GPT4IFX_SCOPE")
        last_err: Optional[str] = None
        if client_id and client_secret:
            try:
                token = self._fetch_service_account_token(client_id=client_id, client_secret=client_secret, scope=scope)
            except Exception as e:
                token = None
                last_err = f"oauth2: {type(e).__name__}: {e}"
            if token:
                self._cached_token = token
                self._cached_at = time.time()
                return token

        # 3) Legacy basic-auth token flow
        user = os.getenv("LLAMA_USER")
        password = os.getenv("LLAMA_PASSWORD")
        if user and password:
            try:
                token = self._fetch_permanent_token(user=user, password=password)
            except Exception as e:
                token = None
                last_err = f"basic: {type(e).__name__}: {e}"
            if token:
                self._cached_token = token
                self._cached_at = time.time()
                return token

        suffix = f" Last error: {last_err}" if last_err else ""
        raise ValueError(
            "No GPT4IFX token available. Set GPT4IFX_CLIENT_ID/GPT4IFX_CLIENT_SECRET (service account) "
            "or set GPT4IFX_API_KEY (manual bearer token), or set LLAMA_USER/LLAMA_PASSWORD (legacy)."
            + suffix
        )


class GPT4IFXClient:
    """
    Wrapper for GPT4IFX API with:
    - Bearer token authentication (2-hour expiry handling)
    - Automatic retries on failures
    - Model fallback (gpt-4.1 → gpt-4.1-nano)
    - Certificate validation (ca-bundle.crt)
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://<your-llm-endpoint>",
        ca_bundle_path: Optional[str] = None,
        primary_model: str = None,
        fallback_model: str = None,
        max_retries: int = 3,
        timeout: int = 120
    ):
        """
        Initialize GPT4IFX client
        
        Args:
            api_key: Bearer token (get from GPT4IFX docs page)
            base_url: GPT4IFX base URL (default: production endpoint)
            ca_bundle_path: Path to ca-bundle.crt certificate
            primary_model: First choice model (default: gpt-4.1)
            fallback_model: Backup model if primary fails (default: gpt-4.1-nano)
            max_retries: Number of retry attempts
            timeout: Request timeout in seconds
        """
        # Token selection:
        # - Prefer permanent token flow if LLAMA_USER/LLAMA_PASSWORD set
        # - Fall back to GPT4IFX_API_KEY (temporary token)
        self.token_provider = TokenProvider(base_url=base_url, ca_bundle_path=ca_bundle_path, timeout=timeout)
        self.api_key = self.token_provider.get_token(api_key=api_key)

        # Avoid printing any secrets
        if os.getenv("GPT4IFX_CLIENT_ID") and os.getenv("GPT4IFX_CLIENT_SECRET"):
            token_source = "service-account (client-credentials)"
        elif os.getenv("LLAMA_USER") and os.getenv("LLAMA_PASSWORD"):
            token_source = "legacy basic-auth (LLAMA_USER/LLAMA_PASSWORD)"
        else:
            token_source = "manual bearer token (GPT4IFX_API_KEY/api_key)"
        # Do not print token material (even masked) in normal operation.
        # Use src.cli doctor / probe mode for safe diagnostics.

        
        self.base_url = base_url
        # Resolve model defaults from env so we adapt to GPT4IFX subscription
        # changes without editing code. The doctor probe always uses gpt-5.2
        # so that is the most reliable default for this account today.
        self.primary_model = (
            primary_model
            or os.getenv("THESIS_LLM_PRIMARY_MODEL")
            or "gpt-5.2"
        )
        self.fallback_model = (
            fallback_model
            or os.getenv("THESIS_LLM_FALLBACK_MODEL")
            or "gpt-5.2-mini"
        )
        self.max_retries = max_retries
        self.timeout = timeout
        # Sticky flag: once the server tells us this model needs
        # `max_completion_tokens` (newer gpt-5.x/o-series), remember it so
        # every subsequent call skips the wasted 400 round-trip.
        self._use_completion_tokens = False
        
        # Configure httpx client with certificate validation
        # GPT4IFX uses a self-signed cert so we MUST provide verify=False
        # or a valid CA bundle path.
        if ca_bundle_path:
            if not os.path.exists(ca_bundle_path):
                raise FileNotFoundError(f"Certificate not found: {ca_bundle_path}")
            verify_setting = ca_bundle_path
        else:
            # Check for env-var override, otherwise disable verification
            env_ca = os.getenv("GPT4IFX_CA_BUNDLE")
            if env_ca and os.path.exists(env_ca):
                verify_setting = env_ca
            else:
                verify_setting = False

        http_client = httpx.Client(verify=verify_setting, timeout=timeout)

        # Bearer auth header — GPT4IFX requires this in addition to api_key
        default_headers = {"Authorization": f"Bearer {self.api_key}"}
        
        # Initialize OpenAI client with custom config
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=base_url,
            default_headers=default_headers,
            http_client=http_client,
            max_retries=0  # We handle retries manually
        )
        
        self.token_created_at = time.time()
        if os.getenv("THESIS_GPT4IFX_LOG_INIT", "0") == "1":
            print(f"✅ GPT4IFX Client initialized (model: {primary_model}, fallback: {fallback_model})")

    
    def _check_token_expiry(self):
        """Check if token is close to 2-hour expiry"""
        elapsed = time.time() - self.token_created_at
        if elapsed > 7000:  # ~1h 56m (leave 4min buffer)
            print("⚠️  Token expiring soon! Refresh your Bearer token from GPT4IFX docs.")
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        use_fallback: bool = True,
        **kwargs
    ) -> str:
        """
        Send chat completion request with automatic retries and fallback
        
        Args:
            messages: List of message dicts [{"role": "user", "content": "..."}]
            model: Model to use (None = use primary_model)
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Max response length
            use_fallback: Whether to try fallback model on failure
            **kwargs: Additional OpenAI API parameters
        
        Returns:
            str: Response content from LLM
        """
        self._check_token_expiry()
        
        model = model or self.primary_model
        last_error = None
        # Some newer models (gpt-5.x, o-series) require max_completion_tokens
        # instead of max_tokens.  We use the sticky instance flag so once we
        # learn the server's preference we never waste a 400 again.
        use_completion_tokens = self._use_completion_tokens

        for attempt in range(self.max_retries):
            try:
                # New OpenAI-style models (gpt-5.x, o-series) reject `max_tokens` and want
                # `max_completion_tokens` instead. The current openai SDK does NOT accept
                # `max_completion_tokens` as a typed kwarg → TypeError. We work around this
                # by routing the param through `extra_body`, which the SDK forwards
                # verbatim in the JSON payload.
                if use_completion_tokens:
                    create_kwargs = dict(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        extra_body={"max_completion_tokens": max_tokens},
                        **kwargs,
                    )
                else:
                    create_kwargs = dict(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **kwargs,
                    )
                response = self.client.chat.completions.create(**create_kwargs)
                return response.choices[0].message.content

            except (OpenAIError, TypeError) as e:
                last_error = e
                err_str = str(e)
                print(f"⚠️  Attempt {attempt + 1}/{self.max_retries} failed: {err_str}")

                # Either: server says "use max_completion_tokens" (OpenAIError 400),
                # OR: SDK rejected our kwarg name (TypeError on max_completion_tokens).
                # In both cases flip to extra_body path and retry immediately.
                triggers_completion_fix = (
                    ("max_tokens" in err_str and "max_completion_tokens" in err_str)
                    or "max_completion_tokens" in err_str
                )
                if triggers_completion_fix and not use_completion_tokens:
                    print("🔧 Switching to max_completion_tokens via extra_body")
                    use_completion_tokens = True
                    self._use_completion_tokens = True  # remember for next call
                    continue

                # If primary model fails and we haven't tried fallback yet
                if use_fallback and model == self.primary_model and attempt < self.max_retries - 1:
                    print(f"🔄 Switching to fallback model: {self.fallback_model}")
                    model = self.fallback_model
                    use_completion_tokens = False  # reset for new model
                    continue
                
                # Exponential backoff
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"⏳ Retrying in {wait_time}s...")
                    time.sleep(wait_time)
        
        raise Exception(f"All {self.max_retries} attempts failed. Last error: {last_error}")
    

    def list_models(self) -> List[Dict[str, Any]]:
        """List available model IDs from the GPT4IFX gateway.

        This uses the OpenAI-compatible `/models` endpoint exposed by GPT4IFX.
        """

        self._check_token_expiry()
        resp = self.client.models.list()
        # openai>=1.x returns a page object with `.data` of Model objects.
        data = getattr(resp, "data", [])
        out: List[Dict[str, Any]] = []
        for m in data:
            mid = getattr(m, "id", None)
            if mid:
                out.append({"id": mid})
        return out
        """
        Test connectivity to GPT4IFX API with specified models
        
        Args:
            models: List of model names to test (None = test primary + fallback)
        
        Returns:
            Dict mapping model names to success status
        """
        if models is None:
            models = [self.primary_model, self.fallback_model]
        
        results = {}
        for model in models:
            try:
                response = self.chat_completion(
                    messages=[{"role": "user", "content": "Hello, this is a test message."}],
                    model=model,
                    max_tokens=50,
                    use_fallback=False  # Don't fallback during test
                )
                results[model] = True
                print(f"✅ {model}: Working (response length: {len(response)} chars)")
            except Exception as e:
                results[model] = False
                print(f"❌ {model}: Failed ({str(e)})")
        
        return results
    
    def embed_text(
        self,
        text: str,
        model: str = "text-embedding-3-small",
    ) -> List[float]:
        """Generate an embedding vector for a single text.

        Notes:
        - Skips empty/whitespace-only inputs (caller bug or empty file).
        - Handles rate limiting (429) with exponential backoff + jitter.

        Returns:
            Embedding vector (e.g., 1536 dims for text-embedding-3-small)
        """
        self._check_token_expiry()

        # Avoid hard failures on empty files / empty chunks.
        if text is None:
            raise ValueError("embed_text: text is None")
        if not str(text).strip():
            raise ValueError("embed_text: empty input text")

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self.client.embeddings.create(model=model, input=text)
                return response.data[0].embedding

            except Exception as e:
                last_error = e

                # Exponential backoff (with jitter) for rate limits and transient errors.
                if attempt < self.max_retries - 1:
                    base = 2 ** attempt
                    # cap sleep to keep UX sane
                    wait_time = min(60.0, float(base))
                    # light jitter so parallel runs don't synchronize
                    try:
                        import random

                        wait_time = wait_time * (0.75 + 0.5 * random.random())
                    except Exception:
                        pass

                    print(
                        f"⚠️  Embedding attempt {attempt + 1}/{self.max_retries} failed: {str(e)}; sleeping {wait_time:.1f}s"
                    )
                    time.sleep(wait_time)
                else:
                    print(f"⚠️  Embedding attempt {attempt + 1}/{self.max_retries} failed: {str(e)}")

        raise Exception(f"Failed to embed text after {self.max_retries} attempts: {last_error}")


# Convenience function for quick initialization
def create_client(
    api_key: Optional[str] = None,
    ca_bundle_path: Optional[str] = None
) -> GPT4IFXClient:
    """
    Quick client initialization
    
    Usage:
        client = create_client(api_key="your-token", ca_bundle_path="path/to/ca-bundle.crt")
        response = client.chat_completion([{"role": "user", "content": "Hello!"}])
    """
    return GPT4IFXClient(api_key=api_key, ca_bundle_path=ca_bundle_path)


if __name__ == "__main__":
    # Test script
    print("=" * 60)
    print("GPT4IFX Client Test")
    print("=" * 60)
    
    # Check for environment variables
    api_key = os.getenv("GPT4IFX_API_KEY")
    ca_bundle = os.getenv("GPT4IFX_CA_BUNDLE", "ca-bundle.crt")
    
    if not api_key:
        print("\n❌ ERROR: GPT4IFX_API_KEY environment variable not set!")
        print("\nHow to fix:")
        print("1. Get your Bearer token from: https://<your-llm-endpoint>/docs")
        print("2. Set environment variable:")
        print("   PowerShell: $env:GPT4IFX_API_KEY='your-token-here'")
        print("   Bash: export GPT4IFX_API_KEY='your-token-here'")
        exit(1)
    
    try:
        # Initialize client
        client = create_client(api_key=api_key, ca_bundle_path=ca_bundle if os.path.exists(ca_bundle) else None)
        
        # Test all models
        print("\n🧪 Testing all available models...\n")
        models_to_test = ["gpt-4o", "gpt-4o-mini", "o3-mini", "gpt-5"]
        results = client.test_connection(models=models_to_test)
        
        # Summary
        print("\n" + "=" * 60)
        print("Test Summary:")
        working_models = [m for m, status in results.items() if status]
        print(f"✅ Working models: {', '.join(working_models)}")
        failed_models = [m for m, status in results.items() if not status]
        if failed_models:
            print(f"❌ Failed models: {', '.join(failed_models)}")
        print("=" * 60)
        
        # Test embedding
        print("\n🧪 Testing embedding model...")
        embedding = client.embed_text("Test embedding", model="text-embedding-3-small")
        print(f"✅ Embedding generated: {len(embedding)} dimensions")
        
    except Exception as e:
        print(f"\n❌ Fatal error: {str(e)}")
        exit(1)

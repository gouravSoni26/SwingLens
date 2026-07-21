"""Named constants for the Supabase secrets keys used by the email-signup feature.

Read lazily from st.secrets inside functions at P3 — never at module import
time, so this stays importable in the test env without secrets configured.
"""

SUPABASE_URL_KEY = "SUPABASE_URL"
SUPABASE_ANON_KEY_KEY = "SUPABASE_ANON_KEY"

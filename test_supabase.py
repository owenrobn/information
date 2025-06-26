import os
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

print("=== SUPABASE DEBUG TEST ===")
print(f"URL: '{SUPABASE_URL}'")
print(f"Key length: {len(SUPABASE_KEY)}")
print(f"Key preview: '{SUPABASE_KEY[:50]}...'")
print()

# Test 1: Direct HTTP Request
print("TEST 1: Direct HTTP Request")
try:
    url = f"{SUPABASE_URL}/rest/v1/"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    
    response = requests.get(url, headers=headers, timeout=10)
    print(f"✅ HTTP Status: {response.status_code}")
    print(f"✅ Response: {response.text[:200]}...")
    
except Exception as e:
    print(f"❌ HTTP Error: {e}")

print()

# Test 2: Supabase Python Client
print("TEST 2: Supabase Python Client")
try:
    from supabase import create_client, Client
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Client created successfully")
    
    # Try a simple query
    result = supabase.table("user_sessions").select("count", count="exact").execute()
    print(f"✅ Query successful: {result}")
    
except Exception as e:
    print(f"❌ Client Error: {e}")
    print(f"❌ Error type: {type(e).__name__}")
    
    # Print more error details
    if hasattr(e, 'code'):
        print(f"❌ Error code: {e.code}")
    if hasattr(e, 'message'):
        print(f"❌ Error message: {e.message}")
    if hasattr(e, 'details'):
        print(f"❌ Error details: {e.details}")

print()

# Test 3: Check if table exists
print("TEST 3: Check Table Existence")
try:
    url = f"{SUPABASE_URL}/rest/v1/user_sessions?select=count"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Prefer": "count=exact"
    }
    
    response = requests.get(url, headers=headers, timeout=10)
    print(f"Table check status: {response.status_code}")
    if response.status_code != 200:
        print(f"Table error response: {response.text}")
    else:
        print("✅ Table exists and accessible")
        
except Exception as e:
    print(f"❌ Table check error: {e}")
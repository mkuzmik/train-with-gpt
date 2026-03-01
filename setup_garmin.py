#!/usr/bin/env python3
"""Setup Garmin Connect authentication.

This script helps you authenticate with Garmin Connect and save OAuth tokens.
Run this once, and the MCP server will use the saved tokens (valid for 1 year).
"""

import json
import sys
from pathlib import Path
from garminconnect import Garmin, GarminConnectAuthenticationError

def main():
    """Run Garmin authentication setup."""
    print("🏃 Garmin Connect Authentication Setup")
    print("=" * 50)
    
    # Load config to get credentials
    config_file = Path.home() / ".config" / "train-with-gpt" / "config.json"
    
    if not config_file.exists():
        print(f"❌ Config file not found: {config_file}")
        print("\nPlease create it with:")
        print('  {"garminEmail": "your@email.com", "garminPassword": "yourpassword"}')
        sys.exit(1)
    
    with open(config_file) as f:
        config = json.load(f)
    
    email = config.get("garminEmail")
    password = config.get("garminPassword")
    
    if not email or not password:
        print("❌ garminEmail and garminPassword not found in config")
        sys.exit(1)
    
    print(f"\n📧 Email: {email}")
    print("🔐 Password: ***")
    
    token_store = Path.home() / ".garminconnect"
    
    try:
        print("\n🔄 Attempting to login to Garmin Connect...")
        
        # Initialize with MFA support
        client = Garmin(email=email, password=password, is_cn=False, return_on_mfa=True)
        result1, result2 = client.login()
        
        if result1 == "needs_mfa":
            print("\n🔐 MFA Required!")
            mfa_code = input("Enter your MFA code: ")
            
            try:
                client.resume_login(result2, mfa_code)
                print("✅ MFA verification successful!")
            except Exception as e:
                print(f"❌ MFA verification failed: {e}")
                sys.exit(1)
        else:
            print("✅ Login successful!")
        
        # Save tokens
        token_store.mkdir(parents=True, exist_ok=True)
        client.garth.dump(str(token_store))
        
        # Verify by getting profile
        profile = client.get_full_name()
        
        print(f"\n✅ Authentication complete!")
        print(f"👤 Connected as: {profile}")
        print(f"💾 Tokens saved to: {token_store}")
        print(f"⏰ Valid for: 1 year")
        print(f"\nYou can now use 'connect_garmin' and 'get_sleep_data' in Claude!")
        
    except GarminConnectAuthenticationError as e:
        print(f"\n❌ Authentication failed: {e}")
        print("\nPlease check your credentials in the config file.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

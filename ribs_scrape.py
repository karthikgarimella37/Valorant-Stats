import requests
import pandas as pd
import sys
import io

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_URL = "https://be-prod.rib.gg/v1"

# Resources to fetch - trying multiple endpoint patterns
RESOURCES = {
    "teams": [
        {"url": "/teams/all?take=5", "name": "Teams (all)"},
        {"url": "/teams?results=5", "name": "Teams (paginated)"}
    ],
    "events": [
        {"url": "/events?results=5", "name": "Events"}
    ],
    "series": [
        {"url": "/series?results=5", "name": "Series/Matches"}
    ],
    "players": [
        {"url": "/players/all?take=5", "name": "Players (all)"},
        {"url": "/players?results=5", "name": "Players (paginated)"}
    ],
    "agents": [
        {"url": "/agents/all?take=5", "name": "Agents (all)"},
        {"url": "/agents?results=5", "name": "Agents (paginated)"}
    ],
    "maps": [
        {"url": "/maps/all?take=5", "name": "Maps (all)"},
        {"url": "/maps?results=5", "name": "Maps (paginated)"}
    ],
    "weapons": [
        {"url": "/weapons/all?take=5", "name": "Weapons (all)"},
        {"url": "/weapons?results=5", "name": "Weapons (paginated)"}
    ]
}

def fetch_data(endpoint_info):
    """Fetch data from an endpoint"""
    url = f"{BASE_URL}{endpoint_info['url']}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            
            # Handle different response formats
            if isinstance(data, list):
                return data[:5]  # Direct array
            elif isinstance(data, dict) and 'data' in data:
                return data['data'][:5]  # Paginated response
            elif isinstance(data, dict):
                return [data]  # Single object
            return None
        return None
    except Exception as e:
        return None

def display_dataframe(df, title):
    """Display a DataFrame with a nice header"""
    print("\n" + "=" * 100)
    print(f"{title}")
    print("=" * 100)
    
    if df is not None and not df.empty:
        # Configure pandas display options for better terminal output
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', None)
        pd.set_option('display.max_colwidth', 50)
        
        print(df.to_string(index=False))
        print(f"\nShape: {df.shape[0]} rows x {df.shape[1]} columns")
        print(f"Columns: {', '.join(df.columns.tolist())}")
    else:
        print("[NO DATA - Endpoint not available or returned empty response]")

def main():
    print("=" * 100)
    print("RIB.GG API DATA VIEWER - First 5 Records of Each Resource")
    print("=" * 100)
    
    results_summary = []
    
    for resource_name, endpoints in RESOURCES.items():
        print(f"\n\nFetching {resource_name.upper()}...")
        
        data = None
        working_endpoint = None
        
        # Try each endpoint pattern until one works
        for endpoint_info in endpoints:
            data = fetch_data(endpoint_info)
            if data:
                working_endpoint = endpoint_info['name']
                break
        
        if data:
            df = pd.DataFrame(data)
            display_dataframe(df, f"{resource_name.upper()} - {working_endpoint}")
            results_summary.append({
                "Resource": resource_name,
                "Status": "✓ Working",
                "Endpoint": working_endpoint,
                "Records": len(data)
            })
        else:
            print(f"\n{'=' * 100}")
            print(f"{resource_name.upper()} - NOT AVAILABLE")
            print(f"{'=' * 100}")
            print("[Endpoint returned 404 or error - data not accessible via API]")
            results_summary.append({
                "Resource": resource_name,
                "Status": "✗ Not Found",
                "Endpoint": "N/A",
                "Records": 0
            })
    
    # Summary table
    print("\n\n" + "=" * 100)
    print("SUMMARY - API ENDPOINTS STATUS")
    print("=" * 100)
    summary_df = pd.DataFrame(results_summary)
    print(summary_df.to_string(index=False))
    
    print("\n" + "=" * 100)
    print("NOTES:")
    print("=" * 100)
    print("""
✓ Working endpoints can be used to fetch data
✗ Not Found endpoints may require:
  - Different URL patterns (use Browser DevTools to discover)
  - Authentication/API keys
  - Or they may not be publicly available

To discover more endpoints:
1. Visit https://rib.gg in your browser
2. Press F12 → Network tab → Filter by Fetch/XHR
3. Click around the website to see API calls
4. Copy the endpoint URLs you find

See 'BROWSER_DEVTOOLS_GUIDE.md' for detailed instructions.
    """)

if __name__ == "__main__":
    main()

import os
import sys
import json

# Add current directory to path
sys.path.append(os.getcwd())

from app import app, APP_SECRET

def test_admin_dashboard():
    print("Testing Enhanced Admin Dashboard...")
    
    with app.test_request_context():
        # Test Authorized
        with app.test_client() as client:
            res = client.get(f'/admin/activity?s={APP_SECRET}')
            print(f"Correct key: {res.status_code}")
            
            if res.status_code == 200:
                print("Admin Dashboard SUCCESSFUL")
                # print(res.data.decode('utf-8')[:500]) # Peek at HTML
            else:
                print("Admin Dashboard FAILED")

if __name__ == "__main__":
    test_admin_dashboard()

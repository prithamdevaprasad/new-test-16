#!/usr/bin/env python3
"""
Debug script to check coordinate extraction in real-time
"""

import requests
import json

BASE_URL = "https://svg-connector-fix.preview.emergentagent.com/api"

def debug_coordinates():
    print("🔍 Debugging coordinate extraction...")
    
    # Get components
    response = requests.get(f"{BASE_URL}/components", timeout=30)
    if response.status_code != 200:
        print(f"❌ Failed to get components: {response.status_code}")
        return
    
    data = response.json()
    if not data.get("success"):
        print(f"❌ API returned error: {data.get('error')}")
        return
    
    components = data.get("components", [])
    print(f"📊 Total components loaded: {len(components)}")
    
    # Check first component in detail
    if components:
        comp = components[0]
        print(f"\n🔍 Analyzing component: {comp.get('title')}")
        print(f"   Category: {comp.get('category')}")
        print(f"   Fritzing ID: {comp.get('fritzingId')}")
        
        connectors = comp.get("connectors", [])
        print(f"   Connectors: {len(connectors)}")
        
        for i, conn in enumerate(connectors[:5]):  # Show first 5
            print(f"     {i+1}. ID: {conn.get('id')}, svgId: {conn.get('svgId')}, x: {conn.get('x')}, y: {conn.get('y')}")
    
    # Check if any component has non-zero coordinates
    components_with_coords = 0
    for comp in components[:20]:  # Check first 20
        connectors = comp.get("connectors", [])
        has_coords = any(conn.get("x", 0) != 0 or conn.get("y", 0) != 0 for conn in connectors)
        if has_coords:
            components_with_coords += 1
            print(f"✅ {comp.get('title')} has non-zero coordinates")
    
    print(f"\n📈 Components with non-zero coordinates: {components_with_coords}/20")

if __name__ == "__main__":
    debug_coordinates()
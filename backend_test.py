#!/usr/bin/env python3
"""
Backend API Test Suite for Fritzing Component Pin Rendering Fixes
Tests the new-repo-15 backend API to verify pin rendering fixes are working correctly.
"""

import requests
import json
import sys
import os
from pathlib import Path

# Get the backend URL from frontend .env file
def get_backend_url():
    frontend_env_path = Path("/app/frontend/.env")
    if frontend_env_path.exists():
        with open(frontend_env_path, 'r') as f:
            for line in f:
                if line.startswith('REACT_APP_BACKEND_URL='):
                    return line.split('=', 1)[1].strip()
    return "http://localhost:8001"

BASE_URL = get_backend_url()
API_BASE = f"{BASE_URL}/api"

class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
        
    def add_pass(self, test_name):
        self.passed += 1
        print(f"✅ PASS: {test_name}")
        
    def add_fail(self, test_name, error):
        self.failed += 1
        self.errors.append(f"{test_name}: {error}")
        print(f"❌ FAIL: {test_name} - {error}")
        
    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"TEST SUMMARY: {self.passed}/{total} tests passed")
        if self.errors:
            print(f"\nFAILED TESTS:")
            for error in self.errors:
                print(f"  - {error}")
        print(f"{'='*60}")
        return self.failed == 0

def test_api_connection():
    """Test basic API connectivity"""
    results = TestResults()
    
    try:
        response = requests.get(f"{API_BASE}/", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if "message" in data:
                results.add_pass("API Connection")
            else:
                results.add_fail("API Connection", "Invalid response format")
        else:
            results.add_fail("API Connection", f"HTTP {response.status_code}")
    except Exception as e:
        results.add_fail("API Connection", str(e))
    
    return results

def test_components_endpoint():
    """Test /api/components endpoint for Fritzing component loading"""
    results = TestResults()
    
    try:
        print(f"Testing components endpoint: {API_BASE}/components")
        response = requests.get(f"{API_BASE}/components", timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            # Check response structure
            if "success" in data and "components" in data:
                if data["success"]:
                    components = data["components"]
                    results.add_pass("Components endpoint returns success")
                    
                    # Check if components are loaded
                    if len(components) > 0:
                        results.add_pass(f"Components loaded ({len(components)} components)")
                        
                        # Test first few components for proper structure
                        for i, component in enumerate(components[:3]):
                            comp_name = component.get("title", f"Component {i+1}")
                            
                            # Check required fields
                            required_fields = ["id", "fritzingId", "title", "connectors"]
                            missing_fields = [field for field in required_fields if field not in component]
                            
                            if not missing_fields:
                                results.add_pass(f"Component structure valid: {comp_name}")
                            else:
                                results.add_fail(f"Component structure: {comp_name}", f"Missing fields: {missing_fields}")
                            
                            # Check connector data
                            connectors = component.get("connectors", [])
                            if connectors:
                                # Check if connectors have proper data including svgId
                                connector_with_svg_id = False
                                connector_with_coords = False
                                
                                for conn in connectors:
                                    if "svgId" in conn and conn["svgId"]:
                                        connector_with_svg_id = True
                                    if "x" in conn and "y" in conn:
                                        connector_with_coords = True
                                
                                if connector_with_svg_id:
                                    results.add_pass(f"SVG ID extraction working: {comp_name}")
                                else:
                                    results.add_fail(f"SVG ID extraction: {comp_name}", "No connectors have svgId field")
                                
                                if connector_with_coords:
                                    results.add_pass(f"Connector coordinates present: {comp_name}")
                                else:
                                    results.add_fail(f"Connector coordinates: {comp_name}", "No connectors have x,y coordinates")
                            else:
                                results.add_fail(f"Connector data: {comp_name}", "No connectors found")
                    else:
                        results.add_fail("Components loading", "No components returned")
                else:
                    results.add_fail("Components endpoint", f"API returned success=false: {data.get('error', 'Unknown error')}")
            else:
                results.add_fail("Components endpoint", "Invalid response structure")
        else:
            results.add_fail("Components endpoint", f"HTTP {response.status_code}: {response.text}")
            
    except Exception as e:
        results.add_fail("Components endpoint", str(e))
    
    return results

def test_svg_pin_parsing():
    """Test SVG pin parsing by examining specific components"""
    results = TestResults()
    
    try:
        # First get components
        response = requests.get(f"{API_BASE}/components", timeout=30)
        if response.status_code != 200:
            results.add_fail("SVG Pin Parsing", "Could not fetch components for testing")
            return results
            
        data = response.json()
        if not data.get("success") or not data.get("components"):
            results.add_fail("SVG Pin Parsing", "No components available for testing")
            return results
        
        components = data["components"]
        
        # Test different component types
        test_components = []
        
        # Look for specific component types
        for comp in components:
            title_lower = comp.get("title", "").lower()
            category_lower = comp.get("category", "").lower()
            
            # Look for resistor
            if ("resistor" in title_lower or "resistor" in category_lower) and len(test_components) < 3:
                test_components.append(("resistor", comp))
            # Look for transistor  
            elif ("transistor" in title_lower or "transistor" in category_lower) and len(test_components) < 3:
                test_components.append(("transistor", comp))
            # Look for IC
            elif ("ic" in title_lower or "ic" in category_lower or "chip" in title_lower) and len(test_components) < 3:
                test_components.append(("ic", comp))
        
        # If we don't have enough specific types, just take first few
        if len(test_components) < 3:
            for i, comp in enumerate(components[:3]):
                if len(test_components) >= 3:
                    break
                comp_type = comp.get("category", "unknown").lower()
                test_components.append((comp_type, comp))
        
        # Test each component
        for comp_type, component in test_components:
            comp_name = component.get("title", f"Component {component.get('id')}")
            connectors = component.get("connectors", [])
            
            if not connectors:
                results.add_fail(f"SVG Pin Parsing ({comp_type})", f"{comp_name}: No connectors found")
                continue
            
            # Check for svgId-based matching
            svg_id_count = sum(1 for conn in connectors if conn.get("svgId"))
            coord_count = sum(1 for conn in connectors if conn.get("x") is not None and conn.get("y") is not None)
            
            if svg_id_count > 0:
                results.add_pass(f"SVG ID extraction ({comp_type}): {comp_name} - {svg_id_count}/{len(connectors)} connectors have svgId")
            else:
                results.add_fail(f"SVG ID extraction ({comp_type})", f"{comp_name}: No connectors have svgId")
            
            if coord_count > 0:
                results.add_pass(f"Pin coordinates ({comp_type}): {comp_name} - {coord_count}/{len(connectors)} connectors have coordinates")
                
                # Check if coordinates are reasonable (not all zeros)
                non_zero_coords = sum(1 for conn in connectors if (conn.get("x", 0) != 0 or conn.get("y", 0) != 0))
                if non_zero_coords > 0:
                    results.add_pass(f"Pin positioning ({comp_type}): {comp_name} - {non_zero_coords} connectors have non-zero coordinates")
                else:
                    results.add_fail(f"Pin positioning ({comp_type})", f"{comp_name}: All coordinates are zero")
            else:
                results.add_fail(f"Pin coordinates ({comp_type})", f"{comp_name}: No connectors have coordinates")
                
    except Exception as e:
        results.add_fail("SVG Pin Parsing", str(e))
    
    return results

def test_svg_rendering():
    """Test SVG rendering endpoints"""
    results = TestResults()
    
    try:
        # First get components to test SVG rendering
        response = requests.get(f"{API_BASE}/components", timeout=30)
        if response.status_code != 200:
            results.add_fail("SVG Rendering", "Could not fetch components for testing")
            return results
            
        data = response.json()
        if not data.get("success") or not data.get("components"):
            results.add_fail("SVG Rendering", "No components available for testing")
            return results
        
        components = data["components"][:3]  # Test first 3 components
        
        for component in components:
            comp_id = component.get("id")
            comp_name = component.get("title", f"Component {comp_id}")
            
            # Test breadboard SVG
            try:
                svg_response = requests.get(f"{API_BASE}/components/{comp_id}/svg/breadboard", timeout=10)
                if svg_response.status_code == 200:
                    svg_content = svg_response.text
                    
                    # Check if it's valid SVG
                    if svg_content.strip().startswith("<?xml") or svg_content.strip().startswith("<svg"):
                        results.add_pass(f"SVG Breadboard rendering: {comp_name}")
                        
                        # Check for viewBox (important for proper scaling)
                        if "viewBox" in svg_content:
                            results.add_pass(f"SVG viewBox present: {comp_name}")
                        else:
                            results.add_fail(f"SVG viewBox: {comp_name}", "No viewBox attribute found")
                            
                        # Check for width/height attributes
                        if 'width=' in svg_content and 'height=' in svg_content:
                            results.add_pass(f"SVG dimensions: {comp_name}")
                        else:
                            results.add_fail(f"SVG dimensions: {comp_name}", "Missing width/height attributes")
                    else:
                        results.add_fail(f"SVG Breadboard rendering: {comp_name}", "Invalid SVG content")
                else:
                    results.add_fail(f"SVG Breadboard rendering: {comp_name}", f"HTTP {svg_response.status_code}")
                    
            except Exception as e:
                results.add_fail(f"SVG Breadboard rendering: {comp_name}", str(e))
                
    except Exception as e:
        results.add_fail("SVG Rendering", str(e))
    
    return results

def test_pin_data_verification():
    """Verify that connector objects include both old x,y coordinates and new svgId field"""
    results = TestResults()
    
    try:
        response = requests.get(f"{API_BASE}/components", timeout=30)
        if response.status_code != 200:
            results.add_fail("Pin Data Verification", "Could not fetch components")
            return results
            
        data = response.json()
        if not data.get("success") or not data.get("components"):
            results.add_fail("Pin Data Verification", "No components available")
            return results
        
        components = data["components"]
        
        # Check first 5 components for proper connector data structure
        for component in components[:5]:
            comp_name = component.get("title", f"Component {component.get('id')}")
            connectors = component.get("connectors", [])
            
            if not connectors:
                continue
                
            # Check each connector for required fields
            for i, connector in enumerate(connectors):
                conn_id = connector.get("id", f"connector{i}")
                
                # Check for old x,y coordinates
                has_coords = "x" in connector and "y" in connector
                # Check for new svgId field
                has_svg_id = "svgId" in connector
                
                if has_coords and has_svg_id:
                    results.add_pass(f"Connector data complete: {comp_name}.{conn_id}")
                elif has_coords and not has_svg_id:
                    results.add_fail(f"Connector data: {comp_name}.{conn_id}", "Missing svgId field")
                elif not has_coords and has_svg_id:
                    results.add_fail(f"Connector data: {comp_name}.{conn_id}", "Missing x,y coordinates")
                else:
                    results.add_fail(f"Connector data: {comp_name}.{conn_id}", "Missing both coordinates and svgId")
                    
    except Exception as e:
        results.add_fail("Pin Data Verification", str(e))
    
    return results

def test_multiple_component_types():
    """Test multiple component types to ensure fixes work across different SVG structures"""
    results = TestResults()
    
    try:
        response = requests.get(f"{API_BASE}/components", timeout=30)
        if response.status_code != 200:
            results.add_fail("Multiple Component Types", "Could not fetch components")
            return results
            
        data = response.json()
        if not data.get("success") or not data.get("components"):
            results.add_fail("Multiple Component Types", "No components available")
            return results
        
        components = data["components"]
        
        # Categorize components by type
        component_types = {}
        for comp in components:
            category = comp.get("category", "Unknown")
            if category not in component_types:
                component_types[category] = []
            component_types[category].append(comp)
        
        # Test at least one component from each category (up to 10 categories)
        tested_categories = 0
        for category, comps in list(component_types.items())[:10]:
            if tested_categories >= 10:
                break
                
            # Test first component in this category
            component = comps[0]
            comp_name = component.get("title", f"Component {component.get('id')}")
            connectors = component.get("connectors", [])
            
            if connectors:
                # Check if this category has working pin extraction
                working_connectors = sum(1 for conn in connectors 
                                       if conn.get("svgId") and 
                                          (conn.get("x") is not None and conn.get("y") is not None))
                
                if working_connectors > 0:
                    results.add_pass(f"Category {category}: {comp_name} - {working_connectors}/{len(connectors)} working connectors")
                else:
                    results.add_fail(f"Category {category}: {comp_name}", "No working connectors found")
            else:
                results.add_fail(f"Category {category}: {comp_name}", "No connectors defined")
                
            tested_categories += 1
            
        if tested_categories > 0:
            results.add_pass(f"Multiple component types tested: {tested_categories} categories")
        else:
            results.add_fail("Multiple component types", "No component categories found")
            
    except Exception as e:
        results.add_fail("Multiple Component Types", str(e))
    
    return results

def main():
    """Run all tests"""
    print("🧪 Starting Backend API Tests for Fritzing Component Pin Rendering Fixes")
    print(f"Testing API at: {API_BASE}")
    print("="*80)
    
    all_results = TestResults()
    
    # Run all test suites
    test_suites = [
        ("API Connection", test_api_connection),
        ("Component Loading", test_components_endpoint),
        ("SVG Pin Parsing", test_svg_pin_parsing),
        ("SVG Rendering", test_svg_rendering),
        ("Pin Data Verification", test_pin_data_verification),
        ("Multiple Component Types", test_multiple_component_types)
    ]
    
    for suite_name, test_func in test_suites:
        print(f"\n🔍 Running {suite_name} Tests...")
        print("-" * 40)
        
        suite_results = test_func()
        
        # Merge results
        all_results.passed += suite_results.passed
        all_results.failed += suite_results.failed
        all_results.errors.extend(suite_results.errors)
    
    # Print final summary
    success = all_results.summary()
    
    if success:
        print("\n🎉 All tests passed! Pin rendering fixes are working correctly.")
        return 0
    else:
        print(f"\n⚠️  {all_results.failed} test(s) failed. Pin rendering fixes need attention.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
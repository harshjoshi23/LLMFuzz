"""
Confluence Crawler for LLM Firmware Fuzzer
Extracts parameter ranges and test specifications from Confluence pages.

Usage:
    crawler = ConfluenceCrawler(base_url, auth_token)
    params = crawler.extract_parameter_ranges(page_id)
"""

import requests
import json
import re
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ParameterRange:
    """Represents a valid range for a parameter"""
    name: str
    min_value: float
    max_value: float
    inclusive_min: bool = True
    inclusive_max: bool = False  # Default: [-1, 1) style
    data_type: str = "float"
    description: str = ""
    
    def is_valid(self, value: float) -> bool:
        """Check if a value is within this range"""
        if self.inclusive_min:
            if value < self.min_value:
                return False
        else:
            if value <= self.min_value:
                return False
                
        if self.inclusive_max:
            if value > self.max_value:
                return False
        else:
            if value >= self.max_value:
                return False
                
        return True
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "min": self.min_value,
            "max": self.max_value,
            "inclusive_min": self.inclusive_min,
            "inclusive_max": self.inclusive_max,
            "type": self.data_type,
            "description": self.description
        }


@dataclass
class TestCase:
    """Represents a test case from Confluence"""
    id: str
    name: str
    parameters: Dict[str, Any]
    expected_output: Dict[str, Any]
    description: str = ""


class ConfluenceCrawler:
    """
    Crawls Confluence pages to extract parameter documentation.
    
    Designed for pages like:
    https://<your-confluence-host>/spaces/PWRLib/pages/2981056962/Test+Cases+for+Hardware+Variant+MXS40PPSS
    """
    
    def __init__(self, base_url: str, auth_token: Optional[str] = None, username: Optional[str] = None, password: Optional[str] = None):
        """
        Initialize the crawler.
        
        Args:
            base_url: Confluence base URL (e.g., https://<your-confluence-host>)
            auth_token: Bearer token for authentication (preferred)
            username: Username for basic auth (alternative)
            password: Password for basic auth (alternative)
        """
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        
        if auth_token:
            self.session.headers['Authorization'] = f'Bearer {auth_token}'
        elif username and password:
            self.session.auth = (username, password)
        
        # Common headers
        self.session.headers['Accept'] = 'application/json'
        self.session.headers['Content-Type'] = 'application/json'
    
    def get_page_content(self, page_id: str) -> Dict:
        """
        Fetch page content from Confluence API.
        
        Args:
            page_id: The Confluence page ID (e.g., "2981056962")
            
        Returns:
            Dict with page title, body content, etc.
        """
        url = f"{self.base_url}/rest/api/content/{page_id}"
        params = {
            'expand': 'body.storage,body.view,metadata.labels'
        }
        
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch page {page_id}: {e}")
            raise
    
    def get_page_by_title(self, space_key: str, title: str) -> Optional[Dict]:
        """
        Find a page by its title within a space.
        
        Args:
            space_key: The space key (e.g., "PWRLib")
            title: The page title
            
        Returns:
            Page data or None if not found
        """
        url = f"{self.base_url}/rest/api/content"
        params = {
            'spaceKey': space_key,
            'title': title,
            'expand': 'body.storage'
        }
        
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            results = response.json().get('results', [])
            return results[0] if results else None
        except requests.RequestException as e:
            logger.error(f"Failed to search for page '{title}': {e}")
            return None
    
    def extract_parameter_ranges(self, page_id: str) -> List[ParameterRange]:
        """
        Extract parameter ranges from a Confluence page.
        
        Parses tables with format like:
        | Parameter | Range |
        | cx_q23[0] | [-1, 1) |
        
        Args:
            page_id: Confluence page ID
            
        Returns:
            List of ParameterRange objects
        """
        page_data = self.get_page_content(page_id)
        html_content = page_data.get('body', {}).get('storage', {}).get('value', '')
        
        if not html_content:
            html_content = page_data.get('body', {}).get('view', {}).get('value', '')
        
        return self._parse_parameter_tables(html_content)
    
    def _parse_parameter_tables(self, html: str) -> List[ParameterRange]:
        """Parse HTML tables to extract parameter ranges."""
        soup = BeautifulSoup(html, 'html.parser')
        parameters = []
        
        # Find all tables
        tables = soup.find_all('table')
        
        for table in tables:
            # Look for tables with parameter/range columns
            headers = [th.get_text(strip=True).lower() for th in table.find_all('th')]
            
            # Check if this looks like a parameter table
            if any('param' in h or 'name' in h for h in headers) and \
               any('range' in h or 'value' in h or 'min' in h for h in headers):
                
                rows = table.find_all('tr')[1:]  # Skip header row
                
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 2:
                        param = self._parse_parameter_row(cells, headers)
                        if param:
                            parameters.append(param)
        
        # Also look for inline parameter definitions
        parameters.extend(self._parse_inline_parameters(soup))
        
        return parameters
    
    def _parse_parameter_row(self, cells: List, headers: List[str]) -> Optional[ParameterRange]:
        """Parse a single row from a parameter table."""
        try:
            # Extract cell texts
            cell_texts = [c.get_text(strip=True) for c in cells]
            
            # Find parameter name
            name = None
            for i, h in enumerate(headers):
                if 'param' in h or 'name' in h:
                    if i < len(cell_texts):
                        name = cell_texts[i]
                    break
            
            if not name:
                name = cell_texts[0]  # Assume first column is name
            
            # Find range specification
            range_text = None
            for i, h in enumerate(headers):
                if 'range' in h or 'value' in h:
                    if i < len(cell_texts):
                        range_text = cell_texts[i]
                    break
            
            if not range_text:
                # Look for range pattern in any cell
                for text in cell_texts[1:]:
                    if re.search(r'[\[\(]-?\d', text):
                        range_text = text
                        break
            
            if range_text:
                return self._parse_range_string(name, range_text)
            
        except Exception as e:
            logger.warning(f"Failed to parse parameter row: {e}")
        
        return None
    
    def _parse_range_string(self, name: str, range_text: str) -> Optional[ParameterRange]:
        """
        Parse a range string like "[-1, 1)" or "[0, 7]" or "0-7".
        
        Supports formats:
        - [-1, 1) - half-open interval
        - [0, 7] - closed interval
        - (0, 1) - open interval
        - 0-7 - simple range
        """
        # Pattern for interval notation: [a, b) or (a, b] etc.
        interval_pattern = r'([\[\(])\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*([\]\)])'
        match = re.search(interval_pattern, range_text)
        
        if match:
            left_bracket = match.group(1)
            min_val = float(match.group(2))
            max_val = float(match.group(3))
            right_bracket = match.group(4)
            
            return ParameterRange(
                name=name,
                min_value=min_val,
                max_value=max_val,
                inclusive_min=(left_bracket == '['),
                inclusive_max=(right_bracket == ']')
            )
        
        # Pattern for simple range: 0-7
        simple_pattern = r'(-?[\d.]+)\s*[-–]\s*(-?[\d.]+)'
        match = re.search(simple_pattern, range_text)
        
        if match:
            min_val = float(match.group(1))
            max_val = float(match.group(2))
            
            return ParameterRange(
                name=name,
                min_value=min_val,
                max_value=max_val,
                inclusive_min=True,
                inclusive_max=True
            )
        
        return None
    
    def _parse_inline_parameters(self, soup: BeautifulSoup) -> List[ParameterRange]:
        """Parse parameter definitions from text content."""
        parameters = []
        
        # Look for patterns like "cx_q23: [-1, 1)" in text
        text = soup.get_text()
        pattern = r'(\w+(?:\[\d+\])?)\s*[:=]\s*([\[\(]-?[\d.]+\s*,\s*-?[\d.]+[\]\)])'
        
        for match in re.finditer(pattern, text):
            name = match.group(1)
            range_text = match.group(2)
            param = self._parse_range_string(name, range_text)
            if param:
                parameters.append(param)
        
        return parameters
    
    def extract_test_cases(self, page_id: str) -> List[TestCase]:
        """
        Extract test case specifications from a Confluence page.
        
        Args:
            page_id: Confluence page ID
            
        Returns:
            List of TestCase objects
        """
        page_data = self.get_page_content(page_id)
        html_content = page_data.get('body', {}).get('storage', {}).get('value', '')
        
        soup = BeautifulSoup(html_content, 'html.parser')
        test_cases = []
        
        # Look for test case sections
        # Common patterns: "TESTCASE1", "Test Case 1", "TC-001"
        headers = soup.find_all(['h1', 'h2', 'h3', 'h4'])
        
        for header in headers:
            header_text = header.get_text(strip=True)
            if re.match(r'(TEST\s*CASE|TC)[\s-]*\d+', header_text, re.IGNORECASE):
                test_case = self._parse_test_case_section(header)
                if test_case:
                    test_cases.append(test_case)
        
        return test_cases
    
    def _parse_test_case_section(self, header_element) -> Optional[TestCase]:
        """Parse a test case section starting from its header."""
        try:
            test_id = header_element.get_text(strip=True)
            
            # Get all siblings until next header
            content_elements = []
            for sibling in header_element.find_next_siblings():
                if sibling.name in ['h1', 'h2', 'h3', 'h4']:
                    break
                content_elements.append(sibling)
            
            # Extract parameters from content
            parameters = {}
            expected_output = {}
            description = ""
            
            for elem in content_elements:
                text = elem.get_text(strip=True)
                
                # Look for parameter assignments
                param_matches = re.findall(r'(\w+)\s*[=:]\s*([\d.e+-]+)', text)
                for name, value in param_matches:
                    try:
                        parameters[name] = float(value)
                    except ValueError:
                        parameters[name] = value
                
                # Look for expected values
                if 'expect' in text.lower() or 'output' in text.lower():
                    output_matches = re.findall(r'(\w+)\s*[=:]\s*([\d.e+-]+)', text)
                    for name, value in output_matches:
                        try:
                            expected_output[name] = float(value)
                        except ValueError:
                            expected_output[name] = value
                
                # Collect description text
                if not parameters and not expected_output:
                    description += text + " "
            
            return TestCase(
                id=test_id,
                name=test_id,
                parameters=parameters,
                expected_output=expected_output,
                description=description.strip()
            )
            
        except Exception as e:
            logger.warning(f"Failed to parse test case section: {e}")
            return None
    
    def export_to_json(self, page_id: str, output_path: str) -> Dict:
        """
        Extract all parameter info from a page and export to JSON.
        
        Args:
            page_id: Confluence page ID
            output_path: Path to save JSON file
            
        Returns:
            Dict with all extracted data
        """
        parameters = self.extract_parameter_ranges(page_id)
        test_cases = self.extract_test_cases(page_id)
        
        data = {
            "source": {
                "confluence_url": f"{self.base_url}/pages/viewpage.action?pageId={page_id}",
                "page_id": page_id,
                "extracted_at": __import__('datetime').datetime.now().isoformat()
            },
            "parameters": [p.to_dict() for p in parameters],
            "test_cases": [
                {
                    "id": tc.id,
                    "name": tc.name,
                    "parameters": tc.parameters,
                    "expected_output": tc.expected_output,
                    "description": tc.description
                }
                for tc in test_cases
            ]
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Exported {len(parameters)} parameters and {len(test_cases)} test cases to {output_path}")
        return data


class LocalDocumentCrawler:
    """
    Crawls local documentation files (Markdown, text) for parameter information.
    Use this when Confluence access is not available.
    """
    
    def __init__(self, root_path: str):
        """
        Initialize with a root directory to search.
        
        Args:
            root_path: Path to documentation directory
        """
        self.root_path = root_path
    
    def extract_parameters_from_file(self, file_path: str) -> List[ParameterRange]:
        """Extract parameter ranges from a local file."""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        parameters = []
        
        # Pattern 1: Table format (markdown)
        # | param | range |
        table_pattern = r'\|\s*(\w+(?:\[\d+\])?)\s*\|\s*([\[\(]-?[\d.]+\s*,\s*-?[\d.]+[\]\)])\s*\|'
        for match in re.finditer(table_pattern, content):
            name = match.group(1)
            range_text = match.group(2)
            param = self._parse_range(name, range_text)
            if param:
                parameters.append(param)
        
        # Pattern 2: Inline format
        # param: [-1, 1)
        inline_pattern = r'(\w+(?:\[\d+\])?)\s*[:=]\s*([\[\(]-?[\d.]+\s*,\s*-?[\d.]+[\]\)])'
        for match in re.finditer(inline_pattern, content):
            name = match.group(1)
            range_text = match.group(2)
            param = self._parse_range(name, range_text)
            if param:
                parameters.append(param)
        
        return parameters
    
    def _parse_range(self, name: str, range_text: str) -> Optional[ParameterRange]:
        """Parse range text into ParameterRange object."""
        pattern = r'([\[\(])\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*([\]\)])'
        match = re.search(pattern, range_text)
        
        if match:
            return ParameterRange(
                name=name,
                min_value=float(match.group(2)),
                max_value=float(match.group(3)),
                inclusive_min=(match.group(1) == '['),
                inclusive_max=(match.group(4) == ']')
            )
        return None
    
    def crawl_directory(self, extensions: List[str] = ['.md', '.txt']) -> List[ParameterRange]:
        """
        Crawl all matching files in the directory tree.
        
        Args:
            extensions: File extensions to process
            
        Returns:
            List of all extracted parameters
        """
        import os
        all_parameters = []
        
        for root, dirs, files in os.walk(self.root_path):
            for file in files:
                if any(file.endswith(ext) for ext in extensions):
                    file_path = os.path.join(root, file)
                    try:
                        params = self.extract_parameters_from_file(file_path)
                        for p in params:
                            p.description = f"Source: {file_path}"
                        all_parameters.extend(params)
                        logger.info(f"Extracted {len(params)} parameters from {file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to process {file_path}: {e}")
        
        return all_parameters


# =============================================================================
# MANUAL PARAMETER DEFINITION (Use when crawling fails)
# =============================================================================

def get_3p3z_parameters_manual() -> List[ParameterRange]:
    """
    Manually defined parameters for 3P3Z filter based on Confluence page:
    https://<your-confluence-host>/spaces/PWRLib/pages/2981056962/
    
    Use this when Confluence API access is not available.
    """
    return [
        # X coefficients (Q23 format, range [-1, 1))
        ParameterRange("cx_q23[0]", -1.0, 1.0, inclusive_min=True, inclusive_max=False,
                      description="X coefficient 0 in Q23 format"),
        ParameterRange("cx_q23[1]", -1.0, 1.0, inclusive_min=True, inclusive_max=False,
                      description="X coefficient 1 in Q23 format"),
        ParameterRange("cx_q23[2]", -1.0, 1.0, inclusive_min=True, inclusive_max=False,
                      description="X coefficient 2 in Q23 format"),
        ParameterRange("cx_q23[3]", -1.0, 1.0, inclusive_min=True, inclusive_max=False,
                      description="X coefficient 3 in Q23 format"),
        
        # Y coefficients (Q23 format, range [-1, 1))
        ParameterRange("cy_q23[0]", -1.0, 1.0, inclusive_min=True, inclusive_max=False,
                      description="Y coefficient 0 in Q23 format"),
        ParameterRange("cy_q23[1]", -1.0, 1.0, inclusive_min=True, inclusive_max=False,
                      description="Y coefficient 1 in Q23 format"),
        ParameterRange("cy_q23[2]", -1.0, 1.0, inclusive_min=True, inclusive_max=False,
                      description="Y coefficient 2 in Q23 format"),
        
        # Scale factors
        ParameterRange("scaleCx", 0, 7, inclusive_min=True, inclusive_max=True,
                      data_type="int", description="X coefficient scale factor"),
        ParameterRange("scaleCy", 0, 7, inclusive_min=True, inclusive_max=True,
                      data_type="int", description="Y coefficient scale factor"),
        
        # Gain factors
        ParameterRange("gIn", 0, 3, inclusive_min=True, inclusive_max=True,
                      data_type="int", description="Input gain factor"),
        ParameterRange("gOut", 0, 7, inclusive_min=True, inclusive_max=True,
                      data_type="int", description="Output gain factor"),
        
        # Limits
        ParameterRange("limit_max", -2147483648, 2147483647, inclusive_min=True, inclusive_max=True,
                      data_type="int32", description="Maximum output limit"),
        ParameterRange("limit_min", -2147483648, 2147483647, inclusive_min=True, inclusive_max=True,
                      data_type="int32", description="Minimum output limit"),
    ]


def export_manual_parameters(output_path: str = "3p3z_parameters.json"):
    """Export manually defined 3P3Z parameters to JSON."""
    params = get_3p3z_parameters_manual()
    
    data = {
        "source": {
            "type": "manual",
            "confluence_reference": "https://<your-confluence-host>/spaces/PWRLib/pages/2981056962/",
            "created_at": __import__('datetime').datetime.now().isoformat()
        },
        "parameters": [p.to_dict() for p in params]
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    
    print(f"Exported {len(params)} parameters to {output_path}")
    return data


# =============================================================================
# USAGE EXAMPLE
# =============================================================================

if __name__ == "__main__":
    # Option 1: Use manual parameters (when Confluence access unavailable)
    print("=== Exporting Manual 3P3Z Parameters ===")
    export_manual_parameters("data/constraints/3p3z_parameters.json")
    
    # Option 2: Crawl Confluence (when access available)
    # crawler = ConfluenceCrawler(
    #     base_url="https://<your-confluence-host>",
    #     auth_token="your_token_here"
    # )
    # crawler.export_to_json("2981056962", "data/constraints/confluence_params.json")
    
    # Option 3: Crawl local documentation
    # local_crawler = LocalDocumentCrawler("data/datasheets/")
    # params = local_crawler.crawl_directory()
    # print(f"Found {len(params)} parameters in local docs")

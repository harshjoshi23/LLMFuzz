"""
GitLab Repository Crawler for LLM Firmware Fuzzer
Extracts documentation, code comments, README files, and metadata from GitLab repos.

Use this when the target repo doesn't have a separate datasheets folder.
It extracts documentation from:
- README.md files
- Code comments (docstrings, header comments)
- .md files anywhere in the repo
- Inline documentation

Usage:
    crawler = GitLabCrawler(gitlab_url, access_token, project_id)
    docs = crawler.extract_all_documentation()
    params = crawler.extract_parameter_info()
"""

import os
import re
import json
import requests
import base64
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """A chunk of documentation extracted from the repo"""
    content: str
    source_file: str
    source_type: str  # "readme", "docstring", "comment", "markdown", "header"
    line_start: int = 0
    line_end: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CodeFunction:
    """Information about a function/method in the codebase"""
    name: str
    file_path: str
    line_number: int
    signature: str
    docstring: str = ""
    parameters: List[Dict[str, str]] = field(default_factory=list)
    return_type: str = ""


@dataclass
class ParameterInfo:
    """Parameter information extracted from code/docs"""
    name: str
    data_type: str
    description: str
    source_file: str
    default_value: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    unit: str = ""


class GitLabCrawler:
    """
    Crawls GitLab repositories to extract documentation and code metadata.
    
    Designed for repos like Farhan's middleware where documentation
    is embedded in code rather than in separate datasheet folders.
    """
    
    def __init__(
        self, 
        gitlab_url: str,
        access_token: str,
        project_id: str,
        branch: str = "main"
    ):
        """
        Initialize GitLab crawler.
        
        Args:
            gitlab_url: GitLab instance URL (e.g., https://<your-gitlab-host>)
            access_token: Personal access token with read_repository scope
            project_id: Project ID or URL-encoded path (e.g., "123" or "group%2Fproject")
            branch: Branch to crawl (default: main)
        """
        self.gitlab_url = gitlab_url.rstrip('/')
        self.access_token = access_token
        self.project_id = project_id
        self.branch = branch
        
        self.session = requests.Session()
        self.session.headers['PRIVATE-TOKEN'] = access_token
        
        self._file_cache: Dict[str, str] = {}
    
    @property
    def api_url(self) -> str:
        """GitLab API base URL"""
        return f"{self.gitlab_url}/api/v4"
    
    def _api_get(self, endpoint: str, params: Dict = None) -> Any:
        """Make a GET request to GitLab API"""
        url = f"{self.api_url}{endpoint}"
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()
    
    def get_file_content(self, file_path: str) -> str:
        """
        Get content of a file from the repository.
        
        Args:
            file_path: Path to file in repository
            
        Returns:
            File content as string
        """
        if file_path in self._file_cache:
            return self._file_cache[file_path]
        
        # URL encode the file path
        encoded_path = file_path.replace('/', '%2F')
        
        try:
            endpoint = f"/projects/{self.project_id}/repository/files/{encoded_path}"
            data = self._api_get(endpoint, params={'ref': self.branch})
            
            # Decode base64 content
            content = base64.b64decode(data['content']).decode('utf-8')
            self._file_cache[file_path] = content
            return content
            
        except requests.HTTPError as e:
            logger.warning(f"Failed to get file {file_path}: {e}")
            return ""
    
    def list_files(self, path: str = "", recursive: bool = True) -> List[Dict]:
        """
        List files in repository.
        
        Args:
            path: Directory path (empty for root)
            recursive: Whether to list recursively
            
        Returns:
            List of file info dicts
        """
        endpoint = f"/projects/{self.project_id}/repository/tree"
        params = {
            'ref': self.branch,
            'recursive': str(recursive).lower(),
            'per_page': 100
        }
        if path:
            params['path'] = path
        
        files = []
        page = 1
        
        while True:
            params['page'] = page
            try:
                result = self._api_get(endpoint, params)
                if not result:
                    break
                files.extend(result)
                page += 1
                if len(result) < 100:
                    break
            except requests.HTTPError:
                break
        
        return files
    
    def find_documentation_files(self) -> List[str]:
        """
        Find all documentation files in the repository.
        
        Returns:
            List of file paths that contain documentation
        """
        doc_patterns = [
            r'README\.md$',
            r'readme\.md$',
            r'.*\.md$',
            r'docs/.*',
            r'documentation/.*',
            r'doc/.*',
        ]
        
        all_files = self.list_files()
        doc_files = []
        
        for file_info in all_files:
            if file_info['type'] != 'blob':
                continue
            
            path = file_info['path']
            for pattern in doc_patterns:
                if re.search(pattern, path, re.IGNORECASE):
                    doc_files.append(path)
                    break
        
        return doc_files
    
    def find_source_files(self, extensions: List[str] = None) -> List[str]:
        """
        Find all source code files.
        
        Args:
            extensions: File extensions to include (default: .c, .h, .py)
            
        Returns:
            List of source file paths
        """
        if extensions is None:
            extensions = ['.c', '.h', '.py', '.cpp', '.hpp']
        
        all_files = self.list_files()
        source_files = []
        
        for file_info in all_files:
            if file_info['type'] != 'blob':
                continue
            
            path = file_info['path']
            if any(path.endswith(ext) for ext in extensions):
                source_files.append(path)
        
        return source_files
    
    def extract_markdown_content(self) -> List[DocumentChunk]:
        """Extract content from all markdown files."""
        chunks = []
        md_files = [f for f in self.find_documentation_files() if f.endswith('.md')]
        
        for file_path in md_files:
            content = self.get_file_content(file_path)
            if content:
                chunks.append(DocumentChunk(
                    content=content,
                    source_file=file_path,
                    source_type="markdown",
                    metadata={"repo": self.project_id}
                ))
                logger.info(f"Extracted markdown: {file_path}")
        
        return chunks
    
    def extract_c_documentation(self) -> List[DocumentChunk]:
        """
        Extract documentation from C/C++ source files.
        
        Extracts:
        - File header comments
        - Function docstrings (Doxygen style)
        - Inline comments with parameter info
        """
        chunks = []
        source_files = self.find_source_files(['.c', '.h', '.cpp', '.hpp'])
        
        for file_path in source_files:
            content = self.get_file_content(file_path)
            if not content:
                continue
            
            # Extract file header comment
            header_match = re.match(r'/\*\*[\s\S]*?\*/', content)
            if header_match:
                chunks.append(DocumentChunk(
                    content=header_match.group(0),
                    source_file=file_path,
                    source_type="header",
                    line_start=1,
                    line_end=header_match.group(0).count('\n') + 1
                ))
            
            # Extract Doxygen-style function comments
            doxygen_pattern = r'/\*\*[\s\S]*?\*/\s*(?:static\s+)?(?:inline\s+)?[\w\*\s]+\s+(\w+)\s*\([^)]*\)'
            for match in re.finditer(doxygen_pattern, content):
                chunks.append(DocumentChunk(
                    content=match.group(0),
                    source_file=file_path,
                    source_type="docstring",
                    metadata={"function_name": match.group(1)}
                ))
            
            # Extract parameter definitions from comments
            param_pattern = r'//.*@param\s+(\w+)\s+(.*?)$|/\*.*@param\s+(\w+)\s+(.*?)\*/'
            for match in re.finditer(param_pattern, content, re.MULTILINE):
                param_name = match.group(1) or match.group(3)
                param_desc = match.group(2) or match.group(4)
                chunks.append(DocumentChunk(
                    content=f"Parameter {param_name}: {param_desc}",
                    source_file=file_path,
                    source_type="comment",
                    metadata={"parameter_name": param_name}
                ))
        
        return chunks
    
    def extract_python_documentation(self) -> List[DocumentChunk]:
        """Extract documentation from Python files."""
        chunks = []
        py_files = self.find_source_files(['.py'])
        
        for file_path in py_files:
            content = self.get_file_content(file_path)
            if not content:
                continue
            
            # Extract module docstring
            module_doc_match = re.match(r'^[\s]*["\']["\']["\'](.+?)["\']["\']["\']', 
                                        content, re.DOTALL)
            if module_doc_match:
                chunks.append(DocumentChunk(
                    content=module_doc_match.group(1),
                    source_file=file_path,
                    source_type="docstring",
                    metadata={"type": "module"}
                ))
            
            # Extract function/class docstrings
            func_pattern = r'def\s+(\w+)\s*\([^)]*\):\s*["\']["\']["\'](.+?)["\']["\']["\']'
            for match in re.finditer(func_pattern, content, re.DOTALL):
                chunks.append(DocumentChunk(
                    content=match.group(2),
                    source_file=file_path,
                    source_type="docstring",
                    metadata={"function_name": match.group(1)}
                ))
        
        return chunks
    
    def extract_parameter_info(self) -> List[ParameterInfo]:
        """
        Extract parameter information from code and documentation.
        
        Looks for patterns like:
        - #define PARAM_NAME value  // description
        - const int param_name = value;  // range: [min, max]
        - @param name description
        """
        parameters = []
        source_files = self.find_source_files()
        
        for file_path in source_files:
            content = self.get_file_content(file_path)
            if not content:
                continue
            
            # Pattern 1: #define with comment
            define_pattern = r'#define\s+(\w+)\s+([^\s/]+)\s*(?://\s*(.*))?'
            for match in re.finditer(define_pattern, content):
                name = match.group(1)
                value = match.group(2)
                description = match.group(3) or ""
                
                # Try to extract range from description
                range_match = re.search(r'range[:\s]*\[([^,]+),\s*([^\]]+)\]', 
                                       description, re.IGNORECASE)
                min_val = float(range_match.group(1)) if range_match else None
                max_val = float(range_match.group(2)) if range_match else None
                
                parameters.append(ParameterInfo(
                    name=name,
                    data_type="define",
                    description=description,
                    source_file=file_path,
                    default_value=value,
                    min_value=min_val,
                    max_value=max_val
                ))
            
            # Pattern 2: Variable declarations with range comments
            var_pattern = r'(?:const\s+)?(\w+)\s+(\w+)\s*=\s*([^;]+);\s*(?://\s*(.*))?'
            for match in re.finditer(var_pattern, content):
                dtype = match.group(1)
                name = match.group(2)
                value = match.group(3).strip()
                comment = match.group(4) or ""
                
                # Extract range info
                range_match = re.search(r'[\[\(](-?[\d.]+)[,\s]+(-?[\d.]+)[\]\)]', comment)
                min_val = float(range_match.group(1)) if range_match else None
                max_val = float(range_match.group(2)) if range_match else None
                
                parameters.append(ParameterInfo(
                    name=name,
                    data_type=dtype,
                    description=comment,
                    source_file=file_path,
                    default_value=value,
                    min_value=min_val,
                    max_value=max_val
                ))
        
        return parameters
    
    def extract_function_signatures(self) -> List[CodeFunction]:
        """Extract function signatures from C source files."""
        functions = []
        c_files = self.find_source_files(['.c', '.h'])
        
        for file_path in c_files:
            content = self.get_file_content(file_path)
            if not content:
                continue
            
            # Pattern for C function definitions
            # Handles: return_type function_name(params) { or ;
            func_pattern = r'(?:/\*\*[\s\S]*?\*/\s*)?((?:static\s+)?(?:inline\s+)?[\w\*]+)\s+(\w+)\s*\(([^)]*)\)\s*[{;]'
            
            for match in re.finditer(func_pattern, content):
                return_type = match.group(1).strip()
                func_name = match.group(2)
                params_str = match.group(3).strip()
                
                # Parse parameters
                params = []
                if params_str and params_str != 'void':
                    for param in params_str.split(','):
                        param = param.strip()
                        # Extract type and name
                        parts = param.rsplit(' ', 1)
                        if len(parts) == 2:
                            params.append({
                                'type': parts[0].strip(),
                                'name': parts[1].strip().replace('*', '')
                            })
                
                # Find docstring before function
                docstring = ""
                doc_match = re.search(
                    rf'/\*\*([\s\S]*?)\*/\s*(?:static\s+)?(?:inline\s+)?[\w\*]+\s+{func_name}',
                    content
                )
                if doc_match:
                    docstring = doc_match.group(1).strip()
                
                functions.append(CodeFunction(
                    name=func_name,
                    file_path=file_path,
                    line_number=content[:match.start()].count('\n') + 1,
                    signature=f"{return_type} {func_name}({params_str})",
                    docstring=docstring,
                    parameters=params,
                    return_type=return_type
                ))
        
        return functions
    
    def extract_all_documentation(self) -> List[DocumentChunk]:
        """
        Extract all documentation from the repository.
        
        Returns:
            List of DocumentChunk objects from all sources
        """
        logger.info(f"Extracting documentation from project {self.project_id}")
        
        all_chunks = []
        
        # Markdown files
        md_chunks = self.extract_markdown_content()
        all_chunks.extend(md_chunks)
        logger.info(f"Found {len(md_chunks)} markdown documentation chunks")
        
        # C/C++ documentation
        c_chunks = self.extract_c_documentation()
        all_chunks.extend(c_chunks)
        logger.info(f"Found {len(c_chunks)} C/C++ documentation chunks")
        
        # Python documentation
        py_chunks = self.extract_python_documentation()
        all_chunks.extend(py_chunks)
        logger.info(f"Found {len(py_chunks)} Python documentation chunks")
        
        logger.info(f"Total: {len(all_chunks)} documentation chunks extracted")
        return all_chunks
    
    def export_documentation(self, output_dir: str = "data/extracted_docs"):
        """
        Export all extracted documentation to files.
        
        Args:
            output_dir: Directory to save documentation
        """
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # Extract everything
        doc_chunks = self.extract_all_documentation()
        params = self.extract_parameter_info()
        functions = self.extract_function_signatures()
        
        # Save documentation chunks
        chunks_data = [
            {
                'content': c.content,
                'source_file': c.source_file,
                'source_type': c.source_type,
                'metadata': c.metadata
            }
            for c in doc_chunks
        ]
        with open(f"{output_dir}/documentation_chunks.json", 'w') as f:
            json.dump(chunks_data, f, indent=2)
        
        # Save parameters
        params_data = [
            {
                'name': p.name,
                'type': p.data_type,
                'description': p.description,
                'source_file': p.source_file,
                'default': p.default_value,
                'min': p.min_value,
                'max': p.max_value
            }
            for p in params
        ]
        with open(f"{output_dir}/parameters.json", 'w') as f:
            json.dump(params_data, f, indent=2)
        
        # Save function signatures
        func_data = [
            {
                'name': f.name,
                'file': f.file_path,
                'line': f.line_number,
                'signature': f.signature,
                'docstring': f.docstring,
                'parameters': f.parameters,
                'return_type': f.return_type
            }
            for f in functions
        ]
        with open(f"{output_dir}/functions.json", 'w') as f:
            json.dump(func_data, f, indent=2)
        
        # Create combined markdown for RAG pipeline
        combined_md = f"# Extracted Documentation from {self.project_id}\n\n"
        
        combined_md += "## Parameters\n\n"
        for p in params:
            combined_md += f"- **{p.name}** ({p.data_type}): {p.description}"
            if p.min_value is not None and p.max_value is not None:
                combined_md += f" [Range: {p.min_value} to {p.max_value}]"
            combined_md += "\n"
        
        combined_md += "\n## Functions\n\n"
        for f in functions[:50]:  # Limit to first 50
            combined_md += f"### {f.name}\n"
            combined_md += f"```c\n{f.signature}\n```\n"
            if f.docstring:
                combined_md += f"{f.docstring}\n"
            combined_md += "\n"
        
        combined_md += "\n## Documentation Excerpts\n\n"
        for chunk in doc_chunks[:20]:  # Limit to first 20
            combined_md += f"### From {chunk.source_file}\n"
            combined_md += f"{chunk.content[:500]}...\n\n" if len(chunk.content) > 500 else f"{chunk.content}\n\n"
        
        with open(f"{output_dir}/combined_documentation.md", 'w') as f:
            f.write(combined_md)
        
        logger.info(f"Exported documentation to {output_dir}/")
        return {
            'chunks': len(doc_chunks),
            'parameters': len(params),
            'functions': len(functions)
        }


class LocalRepoCrawler:
    """
    Crawls a local Git repository (cloned on disk).
    Use when GitLab API access is not available.
    """
    
    def __init__(self, repo_path: str):
        """
        Initialize with path to local repository.
        
        Args:
            repo_path: Path to the git repository root
        """
        self.repo_path = Path(repo_path)
        if not self.repo_path.exists():
            raise ValueError(f"Repository path does not exist: {repo_path}")
    
    def get_file_content(self, file_path: str) -> str:
        """Read content from a local file."""
        full_path = self.repo_path / file_path
        if full_path.exists():
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        return ""
    
    def find_documentation_files(self) -> List[str]:
        """Find all documentation files."""
        doc_files = []
        
        for pattern in ['**/*.md', '**/README*', '**/docs/**/*']:
            for path in self.repo_path.glob(pattern):
                if path.is_file():
                    doc_files.append(str(path.relative_to(self.repo_path)))
        
        return list(set(doc_files))
    
    def find_source_files(self, extensions: List[str] = None) -> List[str]:
        """Find all source files."""
        if extensions is None:
            extensions = ['.c', '.h', '.py', '.cpp', '.hpp']
        
        source_files = []
        for ext in extensions:
            for path in self.repo_path.glob(f'**/*{ext}'):
                if path.is_file():
                    source_files.append(str(path.relative_to(self.repo_path)))
        
        return source_files
    
    def extract_all_documentation(self) -> List[DocumentChunk]:
        """Extract all documentation from local repo."""
        chunks = []
        
        # Markdown files
        for file_path in self.find_documentation_files():
            content = self.get_file_content(file_path)
            if content:
                chunks.append(DocumentChunk(
                    content=content,
                    source_file=file_path,
                    source_type="markdown"
                ))
        
        # Source file comments (basic extraction)
        for file_path in self.find_source_files():
            content = self.get_file_content(file_path)
            if not content:
                continue
            
            # Extract header comments
            if file_path.endswith(('.c', '.h', '.cpp', '.hpp')):
                header_match = re.match(r'/\*\*[\s\S]*?\*/', content)
                if header_match:
                    chunks.append(DocumentChunk(
                        content=header_match.group(0),
                        source_file=file_path,
                        source_type="header"
                    ))
        
        return chunks


# ===========================================================================
# USAGE EXAMPLE
# ===========================================================================

if __name__ == "__main__":
    # Example: Use local repo crawler (when GitLab API not available)
    print("="*60)
    print("GitLab/Local Repository Crawler")
    print("="*60)
    
    # For testing, create a mock local repo structure
    import tempfile
    import os
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create mock repo structure
        os.makedirs(f"{tmpdir}/src")
        os.makedirs(f"{tmpdir}/docs")
        
        # Create README
        with open(f"{tmpdir}/README.md", 'w') as f:
            f.write("""# Test Middleware
            
This is a test middleware for 3P3Z filters.

## Parameters
- cx_q23: X coefficient [-1, 1)
- cy_q23: Y coefficient [-1, 1)
""")
        
        # Create source file with documentation
        with open(f"{tmpdir}/src/filter.c", 'w') as f:
            f.write("""/**
 * @file filter.c
 * @brief 3P3Z filter implementation
 */

#define CX_MAX 1.0  // Maximum X coefficient, range: [-1.0, 1.0)
#define CY_MAX 1.0  // Maximum Y coefficient, range: [-1.0, 1.0)

/**
 * @brief Run the 3P3Z filter
 * @param cx X coefficients array
 * @param cy Y coefficients array
 * @return Filter output
 */
int filter_3p3z_run(float* cx, float* cy) {
    // Implementation
    return 0;
}
""")
        
        # Test local crawler
        crawler = LocalRepoCrawler(tmpdir)
        
        print("\nFound documentation files:")
        for f in crawler.find_documentation_files():
            print(f"  - {f}")
        
        print("\nFound source files:")
        for f in crawler.find_source_files():
            print(f"  - {f}")
        
        print("\nExtracted documentation chunks:")
        chunks = crawler.extract_all_documentation()
        for chunk in chunks:
            print(f"  - {chunk.source_file} ({chunk.source_type}): {len(chunk.content)} chars")
        
        print("\nLocal repo crawler test complete!")

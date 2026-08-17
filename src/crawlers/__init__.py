"""
Crawlers module for extracting documentation from various sources.

Supports:
- Confluence pages (via API)
- GitLab repositories (via API or local clone)
- Local documentation folders
- Code comments and docstrings
"""

from .confluence_crawler import (
    ConfluenceCrawler,
    LocalDocumentCrawler,
    ParameterRange,
    TestCase,
    get_3p3z_parameters_manual,
    export_manual_parameters
)

from .gitlab_crawler import (
    GitLabCrawler,
    LocalRepoCrawler,
    DocumentChunk,
    CodeFunction,
    ParameterInfo
)

__all__ = [
    # Confluence
    'ConfluenceCrawler',
    'LocalDocumentCrawler', 
    'ParameterRange',
    'TestCase',
    'get_3p3z_parameters_manual',
    'export_manual_parameters',
    # GitLab
    'GitLabCrawler',
    'LocalRepoCrawler',
    'DocumentChunk',
    'CodeFunction',
    'ParameterInfo',
]

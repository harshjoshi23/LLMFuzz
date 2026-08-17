"""Analysis and automation helpers.

This package contains modules that enable dynamic onboarding of new firmware blocks:
- `header_parser`: lightweight C header parsing (regex-based) to find function signatures
  and parameter structs.
- `constraint_extractor`: infers parameter encodings and ranges (LLM-assisted with
  heuristic fallbacks).
- `model_generator`: generates `input_models/templates/<block>.yaml` for previously
  unseen blocks.
- `block_onboarding`: creates both input-model + harness templates for new blocks.

The implementations are intentionally pragmatic (thesis scope): they aim to be robust
for common embedded C header patterns, without requiring a full C AST.
"""

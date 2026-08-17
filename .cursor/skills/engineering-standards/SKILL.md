---
name: engineering-standards
description: >-
  Apply ENGINEERING_STANDARDS.md for simple technical English, concise chat,
  why-docstrings, process logging, parallelization, and optimized pipelines into
  Supabase (data extraction, Dagster, dbt, file layout, naming, classes, code
  style). Use when writing or editing code, adding functions/classes/models/assets,
  structuring files, or when the user mentions standards, style, naming, logging,
  parallel, performance, or best practices.
---

# Engineering Standards Skill

## Required read

Open and follow `ENGINEERING_STANDARDS.md` at the repo root.

## Workflow

1. Identify the service: **data extraction**, **Dagster**, **dbt**, or shared Python.
2. Apply that section plus **Universal rules** (logging, parallelization, optimization).
3. For every new function/class/asset/model: add a short **why** docstring or SQL header.
4. Process-level functions: log start / progress / done / error for Dagster run discovery.
5. Prefer thread-pool parallel work for independent I/O; justify serial steps.
6. Optimize for a fast path into Supabase analytics tables.
7. Place files only in the paths defined in the standards file.
8. Reply in simple technical English and keep the chat short.

## If standards conflict with existing code

- Prefer matching nearby code for small edits.
- For new modules, follow `ENGINEERING_STANDARDS.md`.
- If a rule should change, update `ENGINEERING_STANDARDS.md` in the same change and note it in `PROJECT_STATUS.md`.

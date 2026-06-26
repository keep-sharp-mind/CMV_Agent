"""
Error Agent Prompts - Prompts for fixing errors found during agent processing.
"""

ANALYZE_PLAN_ERRORS_PROMPT = """You are a data analysis plan expert. Your task is to diagnose validation errors in a plan's dependency graph.

## Analysis Requirements
The following requirements describe what the plan must achieve:
{requirements_text}

## Current Node Definitions
{node_details}

## Current Dependencies
{current_dependencies_json}

## Validation Errors Found
{error_details}

## Dependency Graph Rules (the plan FAILED these rules)
{validation_rules_text}

## Task
Analyze the validation errors above and determine:
1. **root_cause**: Is the problem in the dependency graph (wrong/missing/extra edges), or in the requirements (e.g., a D node is useless, has no useful output, or its task does not align with any requirement, causing orphaned nodes)?
2. **suggestions**: Natural language description of what needs to change and why.
3. **affected_nodes**: List of node IDs most directly affected by the errors.
4. **needs_requirement_change**: true ONLY if a node should be removed, its description/task is fundamentally wrong, or a requirement is missing that would connect orphaned nodes. false if only the dependency edges need fixing.
5. **explanation**: Brief reasoning for your diagnosis.

Output in JSON format ONLY:
```json
{{
  "root_cause": "dependency_graph" or "requirements",
  "suggestions": "Describe what needs to change here...",
  "affected_nodes": ["D3", "V2"],
  "needs_requirement_change": false,
  "explanation": "Brief reasoning..."
}}
```
"""

FIX_DEPENDENCIES_PROMPT = """You are a data analysis plan expert. Fix the dependency graph based on the analysis below.

## Analysis Requirements
{requirements_text}

## Current Node Definitions
{node_details}

## Validation Errors
{error_details}

## Diagnosis
{diagnosis_text}

## Dependency Type Rules (ALLOWED types ONLY)
1. d -> D: D reads from input table d
2. D -> D: D depends on another D's output
3. d -> V: V uses raw input table data directly
4. D -> V: V uses processed data from a D node
5. V -> I: I is triggered from chart V (trigger source)
6. I -> V: I affects chart V (affected target, DIFFERENT from trigger source)

## CRITICAL I Node Rules
- I nodes have ONLY incoming V->I edges and ONLY outgoing I->V edges
- V<->I BIDIRECTIONAL is ILLEGAL
- The same V CANNOT be both trigger source AND affected target for one I node
- I nodes CANNOT connect to other I nodes

## Dependency Graph Validation Rules (ALL must be satisfied)
1. Every V must have exactly ONE incoming d->V or D->V edge
2. The graph MUST be acyclic (no cycles like D1->D2->D1)
3. No isolated nodes except d nodes (every D/V/I must connect to at least one other node)
4. Every D node must have at least one incoming data edge (d->D or D->D)
5. Every D node should be connected to at least one downstream consumer (D>D, D->V)
6. NEVER create D->I, I->D, V->D, or I->I edges

## Task
Output ONLY the corrected `dependencies` array. Add or remove edges as needed. Do NOT modify nodes — only fix the edges.

```json
[
  {{"from": "...", "to": "...", "type": "..."}},
  ...
]
```
"""

FIX_REQUIREMENTS_PROMPT = """You are a data analysis plan expert. Fix the refined requirements based on the analysis below.

## Overall Goal
{goal}

## Current Refined Requirements
{current_requirements_json}

## Current Node Definitions
{node_details}

## Validation Errors
{error_details}

## Diagnosis
{diagnosis_text}

## Task
The validation errors indicate that some requirements lead to problematic nodes (e.g., orphaned nodes, nodes with no useful purpose). Fix the requirements by:
- Removing or merging redundant requirements that produce useless nodes
- Adjusting requirement descriptions so they lead to well-connected nodes
- Do NOT add new requirements unless absolutely necessary
- Keep the total number of requirements between 2-6

Output the corrected requirements as a JSON array. Each requirement has: id, name, description.

```json
[
  {{
    "id": "R1",
    "name": "Requirement name",
    "description": "Brief description of what this requirement analyzes"
  }}
]
```
"""

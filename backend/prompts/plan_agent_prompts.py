SYSTEM_PROMPT = (
    "You are a professional data analysis planner. "
    "You are good at breaking down analysis goals into concrete, executable steps."
)

GENERATE_GOAL_PROMPT = """Based on the following database schema, generate a high-level analysis goal.

Requirements:
1. The goal should be high-level and general, not overly detailed
2. It should describe what kind of analysis we want to do, but not the specific steps
3. Example of a good goal: "Analyze formation characteristics of two teams"
4. Example of a bad goal: "Count the number of each formation and draw a bar chart" (too detailed, this is a step not a goal)
5. Respond in English
6. The goal should be concise, preferably in one sentence

Database Schema:
{schema_text}

{context_section}

Please output ONLY the goal text, nothing else.
"""

REFINE_REQUIREMENTS_PROMPT = """Your task is to break down an overall analysis goal into several refined, specific sub-requirements.

Overall Goal: {goal}

Requirements for the breakdown:
1. Break the goal into 3-6 sub-requirements
2. Each sub-requirement should be a specific, actionable analysis direction
3. The sub-requirements should cover different aspects of the overall goal
4. Example: if goal is "Analyze formation characteristics of two teams", sub-requirements could be:
   - Formation change analysis over time
   - Formation usage rate statistics
   - Formation matchup analysis between two teams
   - Correlation between formation and match results
5. Respond in English
6. Output strictly in JSON format with the following structure:

```json
{{
  "requirements": [
    {{
      "id": "R1",
      "name": "Requirement name",
      "description": "Brief description of what this requirement analyzes"
    }},
    ...
  ]
}}
```

Database Schema (for reference):
{schema_text}

{context_section}
"""

NODES_AND_DEPENDENCIES_PROMPT = """Your task is to design the D/V/I nodes and their dependency graph for a data analysis plan.

Overall Goal: {goal}

Refined Requirements:
{req_text}

Input Data Tables (these are lowercase 'd' nodes - raw input tables, do NOT generate task descriptions for them):
{input_tables_text}

## Node Type Definitions

### d nodes (lowercase) - Input Data Tables
- These are the raw input tables listed above
- They are already numbered d1, d2, ... based on the list above
- Do NOT create new d nodes - use only the ones listed
- Do NOT write task descriptions for d nodes
- They are the source of data for the graph

### D nodes (uppercase) - Data Processing (Intermediate Tables)
- These are intermediate tables created by data processing
- Every D node MUST declare at least one predecessor through d->D or D->D; a D node can never be a graph root
- Each D node must have a detailed task description of HOW to process the data
- Format: D1, D2, D3, ...
- Each D node has:
  - id: "D1", "D2", etc.
  - name: short node name
  - description: brief goal description
  - task: DETAILED implementation task description (what data processing operations to perform)

### V nodes - Visualization
- These are chart visualizations
- Available chart types (you MUST only use these): bar chart, scatter plot, heatmap, line chart
- Format: V1, V2, V3, ...
- Each V node has:
  - id: "V1", "V2", etc.
  - name: short chart name
  - description: what this chart shows
  - chart_type: one of ["bar", "scatter", "heatmap", "line"]

### I nodes - Interaction
- These are interactive elements on charts
- Trigger types (you MUST only use these): select, interval
- Effect types (you MUST only use these): filter, highlight
- Format: I1, I2, I3, ...
- Each I node has:
  - id: "I1", "I2", etc.
  - name: short interaction name
  - description: what this interaction does
  - trigger: "select" or "interval"
  - effect: "filter" or "highlight"

## Dependency Type Rules (MUST FOLLOW)

**Allowed dependency types:**
1. d -> D: D (data processing) reads from input table d
2. D -> D: D node depends on another D node's output
3. d -> V: V (visualization) uses raw input table data directly
4. D -> V: V (visualization) uses processed data from a D node
5. V -> I: An interaction I is triggered from chart V (V is the TRIGGER SOURCE, e.g., click/interval on V)
6. I -> V: Interaction I affects/changes chart V (V is the AFFECTED TARGET, e.g., V gets filtered/highlighted)

**NEVER create these invalid edge types:**
- D -> I: A data processing node CANNOT directly trigger an interaction
- I -> D: An interaction CANNOT be used as data input to processing
- V -> D: A visualization CANNOT feed data back to processing
- I -> I: Interactions CANNOT connect to other interactions

## CRITICAL I Node Edge Direction Rules (MUST FOLLOW)

**I nodes have STRICT one-way edge direction:**
- I nodes MUST have ONLY incoming edges from V nodes (V->I)
- I nodes MUST have ONLY outgoing edges to V nodes (I->V)
- V<->I BIDIRECTIONAL edges are ILLEGAL and MUST be avoided

**Correct pattern:**
- V1 -> I1 (V1 triggers I1 via click/interval)
- I1 -> V2 (I1 affects V2 via filter/highlight)

**Wrong pattern (NEVER create these):**
- V1 -> I1 AND I1 -> V1 (bidirectional = illegal)
- I1 -> V1 (V1 cannot be affected by its own trigger)
- I1 -> I2 (I nodes cannot connect to each other)

**Each I node must:**
- Have at least 1 incoming V->I edge (a trigger source)
- Have at least 1 outgoing I->V edge (an affected target)
- NOT have any I->I connections
- NOT have V->I and I->V to the same V node

## CRITICAL Dependency Graph Validation Rules (ALL MUST BE SATISFIED)

**Rule 1 - Every non-d node needs a predecessor:** Every D, V, and I node MUST have at least one valid incoming edge. Only lowercase d input nodes may have zero predecessors.

**Rule 2 - D predecessor contract:** Every D must have at least one incoming d->D or D->D edge. Creating D3->V3 is not sufficient if D3 itself has no input.

**Rule 3 - V data contract:** Every V must have exactly ONE incoming data edge (d->V or D->V). An I->V edge is an interaction control edge and does not replace the required data predecessor.

**Rule 4 - I predecessor contract:** Every I must have at least one incoming V->I trigger edge and at least one outgoing I->V target edge. Source and target V nodes must be different.

**Rule 5 - No cycles:** The dependency graph must be acyclic. You CANNOT create circular dependencies like D1->D2->D1 or V1->I1->V1.

**Rule 6 - Edge integrity:** Every edge endpoint must reference an existing node, its `type` must exactly match the source and target node types, duplicate/self-loop edges are forbidden, and lowercase d nodes cannot have incoming edges.

**Rule 7 - Useful outputs:** Every D node should have at least one downstream D or V consumer. A D node that produces data no one uses is wasteful.

**Rule 8 - Data feasibility:** Every D task and V chart must be computable from
the fields explicitly present in its upstream data. Never request unavailable
metrics, write phrases such as "not provided" or "if available", invent proxy
metrics, or substitute counts/IDs for performance, quality, effectiveness, or
other absent concepts. Remove an infeasible requirement instead of fabricating
a computation. A scatter plot requires two meaningful varying dimensions.

## Mandatory Dependency Audit Before Responding

Before producing JSON, audit every generated node:
1. List each D node mentally and verify at least one incoming d->D or D->D edge.
2. List each V node and verify exactly one incoming d->V or D->V edge.
3. List each I node and verify at least one incoming V->I and one outgoing I->V edge to a different V.
4. Trace every D/V/I backward. The chain must eventually reach at least one lowercase d source.
5. Verify every edge type equals the actual endpoint types and that no node ID is missing or duplicated.
6. If a node cannot be connected validly, remove that node instead of returning an invalid graph.
7. Reject any D/V pair whose requested metric is absent from the supplied table schemas.

## Important Guidelines

- Make sure the D/V/I nodes collectively address ALL the refined requirements
- Create reasonable number of nodes (3-10 D nodes, 3-8 V nodes, 2-5 I nodes)
- d nodes are only data sources, they appear as dependencies but don't need task descriptions
- The dependency graph should be logically sound
- Build dependencies at the same time as nodes; never create a D/V/I node without immediately assigning its valid predecessor
- Respond in English
- Output strictly in JSON format

```json
{{
  "nodes": {{
    "d": [
      {{
        "id": "d1",
        "name": "table_name",
        "description": "Input data table",
        "source_table": "db_name.table_name"
      }}
    ],
    "D": [
      {{
        "id": "D1",
        "name": "Node name",
        "description": "Goal of this node",
        "task": "Detailed data processing task description, specifying what operations to perform"
      }}
    ],
    "V": [
      {{
        "id": "V1",
        "name": "Chart name",
        "description": "What this chart shows",
        "chart_type": "bar"
      }}
    ],
    "I": [
      {{
        "id": "I1",
        "name": "Interaction name",
        "description": "What this interaction does",
        "trigger": "select",
        "effect": "filter"
      }}
    ]
  }},
  "dependencies": [
    {{
      "from": "d1",
      "to": "D1",
      "type": "d->D"
    }},
    {{
      "from": "D1",
      "to": "D2",
      "type": "D->D"
    }},
    {{
      "from": "D2",
      "to": "V1",
      "type": "D->V"
    }},
    {{
      "from": "V1",
      "to": "I1",
      "type": "V->I"
    }},
    {{
      "from": "I1",
      "to": "V2",
      "type": "I->V"
    }}
  ]
}}
```

Database Schema (for reference):
{schema_text}

{context_section}
"""

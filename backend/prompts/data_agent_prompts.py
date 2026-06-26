SYSTEM_PROMPT_CHAT_JSON = (
    "You are an expert data engineer. "
    "You write clean, correct Python code using pandas for data processing."
)

SYSTEM_PROMPT_GENERATE = (
    "You are an expert data engineer. "
    "You write clean, correct, production-ready Python code using pandas."
)

PROCESSING_CODE_PROMPT = """Generate Python code using pandas to perform the following data processing task.

Target Node:
- ID: {node_id}
- Name: {node_name}
- Description: {node_description}
- Task: {node_task}

Pre-defined Path Variables (these Python variables are set in the execution environment — use them directly in pd.read_csv()):
{path_variables}

Input Table Details (columns, data types, sample rows for reference):
{inputs_json}

Requirements:
1. Read each input table using pd.read_csv(VARIABLE_NAME) where VARIABLE_NAME is one of the pre-defined path variables listed above
2. DO NOT use string literals like 'path_to_your_file.csv', 'data.csv', 'input.csv', or any hardcoded filenames — always reference the pre-defined variable
3. DO NOT create sample data with pd.DataFrame(...) — always read from the actual CSV files using the provided path variables
4. Perform the data processing task described above
5. The final result must be stored in a variable named 'result_df' (a pandas DataFrame)
6. Do NOT include any print statements or plt.show() calls
7. Do NOT write to any files - the result will be saved by the caller
8. Handle missing values appropriately
9. Make sure column names are clean and meaningful
10. Use English for all variable names and comments

Example pattern:
```python
import pandas as pd
df_input = pd.read_csv(INPUT_TABLE_PATH_D1)
# ... processing ...
result_df = df_input
```

Output ONLY the Python code inside ```python ... ``` blocks.
"""

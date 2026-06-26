import json
d = json.load(open(r'D:\CMV_Agent\data\projects\fd4fd3fc-cb43-46a1-9548-92da10343b5a\data_result.json'))
nodes = d.get('processed_nodes', {})
for k, v in nodes.items():
    print(f'D{k}: success={v.get("success")}, has_csv={bool(v.get("output_path"))}, cols={len(v.get("columns",[]))}, error={str(v.get("error","none"))[:80]}')

vis = d.get('processed_vis', {})
for k, v in vis.items():
    meta = v.get('metadata', {})
    print(f'V{k}: success={v.get("success")}, tables={meta.get("used_tables")}, used_fields={meta.get("used_fields")}')

print()
print('d_table_paths:', d.get('d_table_paths', {}))
print('all_table_paths:', list(d.get('all_table_paths', {}).keys()))

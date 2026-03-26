
# save as test_templates_quick.py in platform-backend/

import json
from tooly import ToolRegistry
from template_tools import attach_template_tools

# ✅ Use full registry (so files can be written)
r = ToolRegistry()
attach_template_tools(r)

# 1️⃣ Search template
search_result = r.execute_tool(
    "search_template",
    {"query": "sidebar", "framework": "react"}
)

print("SEARCH RESULT:\n", search_result)

# ✅ Convert string → dict
if isinstance(search_result, str):
    search_result = json.loads(search_result)

# 2️⃣ Extract template_id safely
try:
    template_id = search_result["results"][0]["template_id"]
    print("\n✅ Selected template_id:", template_id)
except Exception as e:
    print("\n❌ ERROR extracting template_id:", e)
    print("FULL RESPONSE:", search_result)
    exit()

# 3️⃣ Use template
use_result = r.execute_tool(
    "use_template",
    {
        "template_id": template_id,
        "target_path": "/workspace/frontend/test_file.jsx",
        "line_number": 100
    }
)

print("\nUSE TEMPLATE RAW RESULT:\n", use_result)

# ✅ Convert string → dict
if isinstance(use_result, str):
    try:
        use_result = json.loads(use_result)
    except:
        print("\n⚠️ Could not parse use_result as JSON")
        exit()

# 4️⃣ Handle all cases properly
if "error" in use_result:
    print("\n❌ TEMPLATE ERROR:\n", use_result["error"])

elif "warning" in use_result:
    print("\n⚠️ WARNING:\n", use_result["warning"])
    
    # This happens when FilesTools is not attached
    if "code" in use_result:
        print("\n🔥 TEMPLATE CODE:\n")
        print(use_result["code"])

elif use_result.get("success"):
    print("\n✅ TEMPLATE WRITTEN SUCCESSFULLY")
    print("📁 Path:", use_result.get("target_path") or use_result.get("destination_path"))

else:
    print("\n⚠️ Unexpected response:\n", use_result)


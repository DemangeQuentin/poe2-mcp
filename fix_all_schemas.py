#!/usr/bin/env python3
"""
Add 'required': [] to ALL tool inputSchemas that don't have it.
This is critical for MCP SDK 2.1.1 JSON Schema validation.
"""
import re

with open('src/mcp_server.py', 'r') as f:
    content = f.read()

# Strategy: Find each tool's inputSchema block and add required if missing

# Pattern to find: name="...", description=..., inputSchema={ ... }
# We'll insert "required": [] right before the final }, of each inputSchema

def add_required_to_schemas(text):
    # Split by tool definitions
    tools_pattern = r'(types\.Tool\(\s*name="[^"]+".+?(?=\n\s*types\.Tool\(|$))'
    
    def fix_tool(tool_block):
        # Check if this tool has an inputSchema
        if 'inputSchema={' not in tool_block:
            return tool_block
        
        # Check if it already has "required"
        if '"required"' in tool_block:
            return tool_block
        
        # Find the inputSchema block boundaries
        match = re.search(r'inputSchema=(\{[^{}]*(?:\{[^}]*\}[^{}]*)*\})', tool_block, re.DOTALL)
        if not match:
            return tool_block
        
        schema = match.group(1)
        
        # Insert "required": [] before the final }
        # The final } should be followed by ,\n                    ),
        modified_schema = schema.rstrip()
        if modified_schema.endswith('}'):
            modified_schema = modified_schema[:-1] + ',\n                        "required": [],\n                    }'
        
        return tool_block.replace(match.group(1), modified_schema)
    
    # Use a different approach: find each inputSchema={ ... } and add required
    lines = text.split('\n')
    output_lines = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        output_lines.append(line)
        
        # If this line contains inputSchema={
        if 'inputSchema={' in line:
            # Track braces and find the closing }
            brace_count = line.count('{') - line.count('}')
            schema_has_required = False
            i += 1
            
            while i < len(lines) and brace_count > 0:
                next_line = lines[i]
                brace_count += next_line.count('{') - next_line.count('}')
                
                if '"required"' in next_line:
                    schema_has_required = True
                
                # If this is the last line of the schema (brace_count == 0 after this)
                if brace_count == 0:
                    if not schema_has_required and '},' in next_line:
                        # Insert "required": [] before the }
                        indent_match = re.match(r'(\s*)', next_line)
                        indent = indent_match.group(1) if indent_match else ''
                        # Modify the line to add required
                        next_line = next_line.replace('},', ',\n' + indent + '"required": [],\n' + indent + '},')
                    output_lines.append(next_line)
                    i += 1
                    break
                else:
                    output_lines.append(next_line)
                    i += 1
        else:
            i += 1
    
    return '\n'.join(output_lines)

fixed_content = add_required_to_schemas(content)

with open('src/mcp_server.py', 'w') as f:
    f.write(fixed_content)

# Verify
required_count = fixed_content.count('"required"')
print(f"✅ Fixed schemas! Found {required_count} 'required' fields")

# Check a few examples
if 'analyze_character' in fixed_content:
    match = re.search(r'name="analyze_character".+?"required":\s*\[[^\]]*\]', fixed_content, re.DOTALL)
    if match:
        print("✅ analyze_character has 'required'")
    else:
        print("❌ analyze_character missing 'required'")

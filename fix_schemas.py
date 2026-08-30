#!/usr/bin/env python3
"""
Add missing 'required': [] to all inputSchema objects
"""
import re

with open('src/mcp_server.py', 'r') as f:
    content = f.read()

# Replace pattern: closing } of inputSchema without 'required'
# Pattern: },\s*\) where there's no 'required' before
#
# We'll do this by:
# 1. Finding each inputSchema block
# 2. Checking if it has 'required'
# 3. If not, insert "required": [] before the closing }

def fix_schemas(text):
    """Add 'required': [] to inputSchemas that don't have it"""
    lines = text.split('\n')
    result = []
    i = 0
    while i < len(lines):
        result.append(lines[i])
        
        # Check if this line contains inputSchema={ 
        if 'inputSchema={' in lines[i]:
            # Track indent and find the matching }
            brace_depth = 0
            has_properties = False
            has_required = False
            schema_end_line = None
            indent = len(lines[i]) - len(lines[i].lstrip())
            
            # Scan forward to find the closing }
            for j in range(i, min(i + 100, len(lines))):
                line_text = lines[j]
                
                if 'inputSchema=' in line_text:
                    brace_depth = 0
                
                # Count braces
                for char in line_text:
                    if char == '{':
                        brace_depth += 1
                    elif char == '}':
                        brace_depth -= 1
                        if brace_depth == 0:
                            schema_end_line = j
                            break
                
                if '"properties"' in line_text:
                    has_properties = True
                if '"required"' in line_text:
                    has_required = True
                
                if schema_end_line is not None:
                    break
            
            # If we found the schema and it has properties but no required
            if schema_end_line is not None and has_properties and not has_required:
                # Read all lines of this schema
                i += 1
                while i < schema_end_line:
                    result.append(lines[i])
                    if '"required"' in lines[i]:
                        has_required = True
                        break
                    i += 1
                
                # If still no required, add it before the closing }
                if not has_required:
                    # Get the line with the closing }
                    closing_line = lines[schema_end_line]
                    # Find indentation
                    close_indent = len(closing_line) - len(closing_line.lstrip())
                    # Insert "required": [] before }
                    modified = closing_line.replace(
                        '},',
                        '    "required": [],\n' + ' ' * close_indent + '},'
                    )
                    result.append(modified)
                    i = schema_end_line + 1
                else:
                    # required was found, just continue
                    result.append(lines[schema_end_line])
                    i = schema_end_line + 1
        else:
            i += 1
    
    return '\n'.join(result)

fixed = fix_schemas(content)

with open('src/mcp_server.py', 'w') as f:
    f.write(fixed)

print("✅ Added 'required': [] to all inputSchemas")

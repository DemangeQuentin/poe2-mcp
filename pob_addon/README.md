# MCP Bridge Addon for Path of Building (PoE2)

This addon enables bidirectional communication between [poe2-mcp](https://github.com/HivemindOverlord/poe2-mcp) and Path of Building, allowing AI-powered build analysis with visual feedback.

## Features

- **Push builds to PoB**: Send character data from poe.ninja directly to PoB for visualization
- **Pull calculations**: Read DPS, EHP, resistances, and other stats from PoB's calculation engine
- **Real-time feedback**: See the impact of suggested changes instantly in PoB
- **Skill management**: Add, modify, or replace skill setups via MCP commands
- **Passive tree access**: Query allocated nodes and modify the tree programmatically

## Installation

### Quick Install

1. Download `MCP_PoB_Addon.zip` from the [releases](https://github.com/HivemindOverlord/poe2-mcp/releases) or from `pob_addon/` folder
2. Extract the zip file
3. Run `install.bat`
4. Follow the prompts

### What Gets Modified

The installer makes minimal changes to your PoB installation:

1. **Adds** the `Addons/MCPBridge/` folder to `src/`
2. **Adds ONE line** to `src/Launch.lua` to load the addon

See `WHAT_THIS_DOES.txt` for complete details on what the installer does.

### Manual Installation

If you prefer not to run the installer:

1. Copy the `Addons` folder to `<PoB Install>/src/`
2. Add this line to `src/Launch.lua` after line ~79:
   ```lua
   pcall(dofile, GetScriptPath()..'/Addons/init.lua') -- MCP Bridge Addon Loader
   ```

## Usage

### With poe2-mcp

Once installed, the addon starts automatically when you launch Path of Building. Use the MCP tools to connect:

```
# In Claude/poe2-mcp
> Connect to PoB
[Uses pob_connect tool]

> Push my character to PoB
[Uses pob_push_character tool with account/character]

> What's my DPS according to PoB?
[Uses pob_pull_calcs tool]
```

### Available Commands

The bridge accepts JSON-RPC commands on port `49085`.

**System / build**
| Command | Description |
|---------|-------------|
| `ping` / `status` | Health check / server status |
| `get_build` | Current build as XML or PoB code |
| `load_build` / `load_build_direct` / `new_build` | Load a build (mode-switch / in-place / empty) |
| `recalculate` | Force a calc refresh (use sparingly — heavy) |

**Calculation output**
| Command | Description |
|---------|-------------|
| `get_calcs` | Key stats (DPS, life, ES, resists, attributes) |
| `get_output` | Only the requested output fields (avoids huge dumps) |
| `get_full_dps` | Full DPS incl. triggered/DoT skills, per-skill list |
| `get_defense_stats` / `get_skill_dps` / `get_raw_output` | Focused defense / per-group DPS / raw output |
| `get_stat_breakdown` | **Modifier-by-modifier "why" for a stat** (defensive/attribute/resist) |
| `compare_with_snapshot` | Diff current calcs vs a saved snapshot |

**Skills**
| Command | Description |
|---------|-------------|
| `get_skills` / `get_skill_parts` | List socket groups / a group's active skills + parts |
| `set_skill_group` | Add/replace a socket group (paste format) |
| `set_group_gems` | Replace a group's gems **in place** |
| `set_main_skill_group` | Set which group is the main skill |
| `set_displayed_skill` | Set the displayed active skill + part (trigger/DoT skills) |

**Passive tree**
| Command | Description |
|---------|-------------|
| `get_passive_tree` | Allocated nodes (class, ascendancy, points) |
| `search_tree_nodes` | Search the full tree by stat keyword(s) |
| `set_passive_node` | Allocate (auto-paths) / deallocate a node |
| `reset_tree` | Reset to class start (for a clean respec) |

**Items / config**
| Command | Description |
|---------|-------------|
| `get_items` | Equipped items + mods |
| `get_config` / `set_config` / `set_config_input` | Read / write config inputs |
| `list_config_options` | Enumerate available config options + values |
| `get_custom_mods` / `set_custom_mods` | Read / write custom modifier text |
| `set_character_level` | Set level (passive-point budget) |

**Character import (Path of Exile API)**
| Command | Description |
|---------|-------------|
| `import_download_list` | Download the account's character list |
| `import_get_state` | Poll import state + character list |
| `import_select_char` | Select a character by name |
| `import_run` | Import `tree` or `items` for the selected character |

> **Tip:** import the **passive tree before items** — importing a tree while a minion-summon is the main skill triggers a PoB crash (see poe2-mcp's bug report to upstream PoB).

### Example JSON-RPC Request

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "get_calcs",
  "params": {}
}
```

### Example Response

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "TotalDPS": 1234567,
    "Life": 4500,
    "EnergyShield": 0,
    "FireResist": 75,
    "ColdResist": 75,
    "LightningResist": 75,
    "ChaosResist": 30
  }
}
```

## Configuration

Edit `src/Addons/MCPBridge/config.lua` to customize:

```lua
MCPConfig.PORT = 49085        -- TCP port (change if conflicts)
MCPConfig.ENABLED = true      -- Master enable/disable
MCPConfig.LOG_COMMANDS = true -- Log commands to console
MCPConfig.AUTO_START = true   -- Start server on PoB launch
```

## Uninstallation

Run `uninstall.bat` or manually:

1. Delete `src/Addons/MCPBridge/` folder
2. Remove the `pcall(dofile...)` line from `src/Launch.lua`
3. (Optional) Restore `src/Launch.lua` from `src/Launch.lua.mcp_backup`

## Security

- **Localhost only**: The server binds to `127.0.0.1` and cannot accept remote connections
- **No external network**: The addon does not make any internet connections
- **Read before install**: All source code is included; review `WHAT_THIS_DOES.txt`
- **Non-destructive**: Your builds are never modified without explicit commands
- **Easy removal**: Uninstaller restores original state completely

## Troubleshooting

### PoB won't start after installation

1. Run `uninstall.bat` to restore original files
2. Check that you have the correct PoB version (PoE2 fork)
3. Report the issue on GitHub with any error messages

### Connection refused

1. Make sure PoB is running
2. Check if another application is using port 49085
3. Try changing the port in `config.lua`

### Commands not working

1. Check PoB's console (F1) for error messages
2. Ensure a build is loaded in PoB
3. Verify JSON-RPC format is correct

## License

MIT License - Same as poe2-mcp

## Credits

- Path of Building (PoE2 Fork): https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2
- poe2-mcp: https://github.com/HivemindOverlord/poe2-mcp

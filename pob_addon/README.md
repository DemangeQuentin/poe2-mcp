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

The bridge accepts JSON-RPC commands on port `49085`:

| Command | Description |
|---------|-------------|
| `ping` | Health check |
| `get_build` | Get current build as XML or PoB code |
| `load_build` | Load a build from XML or PoB code |
| `get_calcs` | Get calculation results (DPS, defenses, etc.) |
| `get_skills` | Get all skill groups and gems |
| `set_skill_group` | Add or modify skill setups |
| `get_passive_tree` | Get allocated passive nodes |
| `set_passive_node` | Allocate or deallocate nodes |
| `get_items` | Get equipped items |
| `set_custom_mods` | Set custom modifier text |
| `get_config` / `set_config` | Read/write configuration |

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

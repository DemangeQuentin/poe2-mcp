# Path of Building MCP Integration Plan

## Executive Summary

This document outlines a complete bidirectional integration between the **poe2-mcp** server and **Path of Building (PoE2 Fork)**. The integration enables:

1. **MCP → PoB**: Push character builds from MCP analysis to PoB for visualization
2. **PoB → MCP**: Pull build data from PoB for AI-powered analysis
3. **Real-time sync**: Live calculation updates as AI suggests changes
4. **Unified workflow**: Seamless transitions between AI analysis and visual planning

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           User's Machine                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐     TCP Socket      ┌────────────────────────────┐    │
│  │   Claude Code    │◄──────────────────► │   Path of Building        │    │
│  │   + poe2-mcp     │     (Port 49085)    │   (PoE2 Fork)             │    │
│  │                  │                      │                           │    │
│  │  ┌────────────┐  │                      │  ┌─────────────────────┐ │    │
│  │  │ MCP Server │  │  JSON-RPC Protocol   │  │ MCP Bridge Module   │ │    │
│  │  │            │  │◄────────────────────►│  │ (New Lua Module)    │ │    │
│  │  └────────────┘  │                      │  └─────────────────────┘ │    │
│  │                  │                      │            │              │    │
│  │  analyze_char    │                      │            ▼              │    │
│  │  optimize_build  │                      │  ┌─────────────────────┐ │    │
│  │  validate_gems   │                      │  │ Build Module        │ │    │
│  │  compare_players │                      │  │ (Existing)          │ │    │
│  │                  │                      │  └─────────────────────┘ │    │
│  └──────────────────┘                      │            │              │    │
│                                            │            ▼              │    │
│                                            │  ┌─────────────────────┐ │    │
│                                            │  │ Calculation Engine  │ │    │
│                                            │  │ (CalcPerform.lua)   │ │    │
│                                            │  └─────────────────────┘ │    │
│                                            └────────────────────────────┘    │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    Shared Build Storage                               │   │
│  │   %USERPROFILE%/Path of Building (PoE2)/Builds/MCP_Synced/           │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Project End Goals

### Phase 1: One-Way Push (MCP → PoB)
**Goal**: User can analyze a character with MCP and view it in PoB

- Generate PoB-compatible XML from character data
- Save builds to PoB's builds folder
- Generate PoB codes for sharing
- User manually opens PoB to see changes

### Phase 2: Bidirectional Sync (MCP ↔ PoB)
**Goal**: Real-time communication between MCP and running PoB instance

- TCP socket server in PoB for receiving commands
- MCP client for sending commands to PoB
- Push build changes from MCP to open PoB
- Pull calculation results from PoB to MCP

### Phase 3: Live Optimization
**Goal**: AI-powered optimization with visual feedback

- AI suggests gear/passive changes
- Changes instantly reflected in PoB
- User can accept/reject changes in PoB
- PoB sends updated calculations back to MCP

### Phase 4: Full Integration
**Goal**: Seamless workflow between AI analysis and visual planning

- PoB plugin/extension for MCP awareness
- In-PoB AI suggestions panel
- Collaborative build editing
- Build history and version control

---

## Technical Implementation Details

### Part 1: Files to Create in Path of Building

#### 1.1 `src/Modules/MCPBridge.lua` (New File)
**Purpose**: Core IPC module for MCP communication

```lua
-- Path of Building (PoE2)
--
-- Module: MCP Bridge
-- Handles communication with external MCP servers via TCP sockets.

local socket = require("socket")
local dkjson = require("dkjson")

local MCPBridge = {}
MCPBridge.__index = MCPBridge

-- Configuration
local DEFAULT_PORT = 49085
local COMMAND_TIMEOUT = 5  -- seconds

-- Command handlers
local handlers = {}

function MCPBridge:new()
    local self = setmetatable({}, MCPBridge)
    self.server = nil
    self.client = nil
    self.running = false
    self.port = DEFAULT_PORT
    return self
end

function MCPBridge:start(port)
    self.port = port or DEFAULT_PORT
    self.server = assert(socket.bind("*", self.port))
    self.server:settimeout(0)  -- Non-blocking
    self.running = true
    ConPrintf("[MCPBridge] Server started on port %d", self.port)
end

function MCPBridge:stop()
    if self.server then
        self.server:close()
        self.server = nil
    end
    self.running = false
    ConPrintf("[MCPBridge] Server stopped")
end

function MCPBridge:poll()
    if not self.running or not self.server then return end

    -- Accept new connections (non-blocking)
    local client = self.server:accept()
    if client then
        client:settimeout(COMMAND_TIMEOUT)
        self:handleClient(client)
        client:close()
    end
end

function MCPBridge:handleClient(client)
    local request, err = client:receive("*l")
    if err then
        ConPrintf("[MCPBridge] Receive error: %s", err)
        return
    end

    local success, command = pcall(dkjson.decode, request)
    if not success or not command then
        self:sendError(client, "Invalid JSON")
        return
    end

    local handler = handlers[command.method]
    if handler then
        local result, err = handler(command.params)
        if err then
            self:sendError(client, err)
        else
            self:sendResult(client, command.id, result)
        end
    else
        self:sendError(client, "Unknown method: " .. tostring(command.method))
    end
end

function MCPBridge:sendResult(client, id, result)
    local response = dkjson.encode({
        jsonrpc = "2.0",
        id = id,
        result = result
    })
    client:send(response .. "\n")
end

function MCPBridge:sendError(client, message)
    local response = dkjson.encode({
        jsonrpc = "2.0",
        error = { code = -1, message = message }
    })
    client:send(response .. "\n")
end

-- Register command handlers
function MCPBridge.registerHandler(method, func)
    handlers[method] = func
end

return MCPBridge
```

#### 1.2 `src/Modules/MCPCommands.lua` (New File)
**Purpose**: Define all MCP command handlers

```lua
-- Path of Building (PoE2)
--
-- Module: MCP Commands
-- Defines handlers for MCP bridge commands.

local MCPCommands = {}

-- GET_BUILD - Returns current build as XML or PoB code
function MCPCommands.getBuild(params)
    local format = params and params.format or "xml"

    if not build then
        return nil, "No build loaded"
    end

    local xmlText = build:SaveDB("code")

    if format == "code" then
        return {
            code = common.base64.encode(Deflate(xmlText)):gsub("+","-"):gsub("/","_"),
            format = "pob_code"
        }
    else
        return {
            xml = xmlText,
            format = "xml"
        }
    end
end

-- LOAD_BUILD - Load a build from XML or PoB code
function MCPCommands.loadBuild(params)
    if not params then
        return nil, "Missing parameters"
    end

    local xmlText
    if params.code then
        -- Decode PoB code to XML
        xmlText = Inflate(common.base64.decode(params.code:gsub("-","+"):gsub("_","/")))
    elseif params.xml then
        xmlText = params.xml
    else
        return nil, "Missing code or xml parameter"
    end

    if not xmlText then
        return nil, "Failed to decode build"
    end

    -- Load the build
    mainObject.main:SetMode("BUILD", false, params.name or "MCP Import", xmlText)
    runCallback("OnFrame")

    return { success = true }
end

-- GET_CALCS - Get calculation output
function MCPCommands.getCalcs(params)
    if not build or not build.calcsTab then
        return nil, "No build loaded"
    end

    runCallback("OnFrame")  -- Ensure calculations are fresh

    local output = build.calcsTab.mainOutput
    local calcsOutput = build.calcsTab.calcsOutput

    -- Return key stats
    return {
        -- Offensive
        TotalDPS = output.TotalDPS,
        CombinedDPS = output.CombinedDPS,
        AverageDamage = output.AverageDamage,
        Speed = output.Speed,
        CritChance = output.CritChance,
        CritMultiplier = output.CritMultiplier,
        HitChance = output.HitChance,

        -- Defensive
        Life = output.Life,
        EnergyShield = output.EnergyShield,
        Mana = output.Mana,
        Armour = output.Armour,
        Evasion = output.Evasion,
        PhysicalDamageReduction = output.PhysicalDamageReduction,
        SpellSuppressionChance = output.SpellSuppressionChance,
        BlockChance = output.BlockChance,

        -- Resistances
        FireResist = output.FireResist,
        ColdResist = output.ColdResist,
        LightningResist = output.LightningResist,
        ChaosResist = output.ChaosResist,

        -- Resources
        Spirit = output.Spirit,
        SpiritReserved = output.SpiritReserved,
        ManaRegen = output.ManaRegen,
        LifeRegen = output.LifeRegen,

        -- Attributes
        Str = output.Str,
        Dex = output.Dex,
        Int = output.Int,

        -- Max Hits
        PhysicalMaximumHitTaken = calcsOutput and calcsOutput.PhysicalMaximumHitTaken,
        FireMaximumHitTaken = calcsOutput and calcsOutput.FireMaximumHitTaken,
        ColdMaximumHitTaken = calcsOutput and calcsOutput.ColdMaximumHitTaken,
        LightningMaximumHitTaken = calcsOutput and calcsOutput.LightningMaximumHitTaken,
        ChaosMaximumHitTaken = calcsOutput and calcsOutput.ChaosMaximumHitTaken,
    }
end

-- SET_SKILL_GROUP - Add or modify skill group
function MCPCommands.setSkillGroup(params)
    if not build or not build.skillsTab then
        return nil, "No build loaded"
    end

    -- Format: "Skill Level/Quality Slot\nSupport Level/Quality Slot\n..."
    local skillText = params.skills
    if not skillText then
        return nil, "Missing skills parameter"
    end

    if params.replace then
        -- Clear existing skills first
        while #build.skillsTab.socketGroupList > 0 do
            build.skillsTab:DeleteSocketGroup(build.skillsTab.socketGroupList[1])
        end
    end

    build.skillsTab:PasteSocketGroup(skillText)
    runCallback("OnFrame")

    return { success = true }
end

-- SET_CONFIG - Set configuration options
function MCPCommands.setConfig(params)
    if not build or not build.configTab then
        return nil, "No build loaded"
    end

    for key, value in pairs(params) do
        if key ~= "method" and key ~= "id" then
            build.configTab.input[key] = value
        end
    end

    build.configTab:BuildModList()
    runCallback("OnFrame")

    return { success = true }
end

-- SET_CUSTOM_MODS - Set custom modifier text
function MCPCommands.setCustomMods(params)
    if not build or not build.configTab then
        return nil, "No build loaded"
    end

    build.configTab.input.customMods = params.mods or ""
    build.configTab:BuildModList()
    runCallback("OnFrame")

    return { success = true }
end

-- GET_PASSIVE_TREE - Get allocated passive nodes
function MCPCommands.getPassiveTree(params)
    if not build or not build.spec then
        return nil, "No build loaded"
    end

    local allocatedNodes = {}
    for nodeId, node in pairs(build.spec.allocNodes) do
        table.insert(allocatedNodes, {
            id = nodeId,
            name = node.name,
            type = node.type,
            stats = node.sd,
        })
    end

    return {
        class = build.spec.curClassName,
        ascendancy = build.spec.curAscendClassName,
        nodes = allocatedNodes,
        totalPoints = build.spec:CountAllocNodes()
    }
end

-- SET_PASSIVE_NODE - Allocate or deallocate a passive node
function MCPCommands.setPassiveNode(params)
    if not build or not build.spec then
        return nil, "No build loaded"
    end

    local nodeId = params.nodeId
    local allocate = params.allocate

    if allocate then
        build.spec:AllocNode(nodeId)
    else
        build.spec:DeallocNode(nodeId)
    end

    build.spec:AddUndoState()
    runCallback("OnFrame")

    return { success = true }
end

-- GET_ITEMS - Get equipped items
function MCPCommands.getItems(params)
    if not build or not build.itemsTab then
        return nil, "No build loaded"
    end

    local items = {}
    for slotName, item in pairs(build.itemsTab.items) do
        if item then
            table.insert(items, {
                slot = slotName,
                name = item.name,
                rarity = item.rarity,
                base = item.baseName,
                mods = item.modList,
            })
        end
    end

    return { items = items }
end

-- PING - Simple health check
function MCPCommands.ping(params)
    return {
        status = "ok",
        version = launch.versionNumber,
        buildLoaded = build ~= nil
    }
end

-- COMPARE_BUILDS - Compare current build with another
function MCPCommands.compareBuilds(params)
    if not build or not build.calcsTab then
        return nil, "No build loaded"
    end

    -- Get current stats
    local currentStats = MCPCommands.getCalcs({})

    -- Temporarily load comparison build
    local savedXml = build:SaveDB("code")
    local comparisonXml

    if params.code then
        comparisonXml = Inflate(common.base64.decode(params.code:gsub("-","+"):gsub("_","/")))
    elseif params.xml then
        comparisonXml = params.xml
    else
        return nil, "Missing comparison build"
    end

    mainObject.main:SetMode("BUILD", false, "Comparison", comparisonXml)
    runCallback("OnFrame")

    local comparisonStats = MCPCommands.getCalcs({})

    -- Restore original build
    mainObject.main:SetMode("BUILD", false, "Restored", savedXml)
    runCallback("OnFrame")

    -- Calculate differences
    local diff = {}
    for key, value in pairs(currentStats) do
        if type(value) == "number" and comparisonStats[key] then
            diff[key] = {
                current = value,
                comparison = comparisonStats[key],
                delta = comparisonStats[key] - value,
                percent = value ~= 0 and ((comparisonStats[key] - value) / value * 100) or 0
            }
        end
    end

    return { comparison = diff }
end

return MCPCommands
```

#### 1.3 `src/Modules/MCPInit.lua` (New File)
**Purpose**: Initialize MCP bridge on startup

```lua
-- Path of Building (PoE2)
--
-- Module: MCP Init
-- Initializes MCP bridge integration.

local MCPBridge = LoadModule("Modules/MCPBridge")
local MCPCommands = LoadModule("Modules/MCPCommands")

local mcpBridge = MCPBridge:new()

-- Register all command handlers
MCPBridge.registerHandler("ping", MCPCommands.ping)
MCPBridge.registerHandler("get_build", MCPCommands.getBuild)
MCPBridge.registerHandler("load_build", MCPCommands.loadBuild)
MCPBridge.registerHandler("get_calcs", MCPCommands.getCalcs)
MCPBridge.registerHandler("set_skill_group", MCPCommands.setSkillGroup)
MCPBridge.registerHandler("set_config", MCPCommands.setConfig)
MCPBridge.registerHandler("set_custom_mods", MCPCommands.setCustomMods)
MCPBridge.registerHandler("get_passive_tree", MCPCommands.getPassiveTree)
MCPBridge.registerHandler("set_passive_node", MCPCommands.setPassiveNode)
MCPBridge.registerHandler("get_items", MCPCommands.getItems)
MCPBridge.registerHandler("compare_builds", MCPCommands.compareBuilds)

-- Start the server
function StartMCPBridge(port)
    mcpBridge:start(port)
end

-- Stop the server
function StopMCPBridge()
    mcpBridge:stop()
end

-- Poll for connections (call from main loop)
function PollMCPBridge()
    mcpBridge:poll()
end

-- Check if running
function IsMCPBridgeRunning()
    return mcpBridge.running
end

return {
    start = StartMCPBridge,
    stop = StopMCPBridge,
    poll = PollMCPBridge,
    isRunning = IsMCPBridgeRunning,
    bridge = mcpBridge
}
```

#### 1.4 Modifications to `src/Modules/Main.lua`
**Purpose**: Integrate MCP bridge into main loop

```lua
-- Add near the top, after other LoadModule calls:
local MCPInit = LoadModule("Modules/MCPInit")

-- Add to OnInit callback (after settings load):
if main.mcpEnabled then
    MCPInit.start(main.mcpPort or 49085)
end

-- Add to OnFrame callback (near the end):
if MCPInit.isRunning() then
    MCPInit.poll()
end

-- Add to OnExit callback:
MCPInit.stop()
```

#### 1.5 Modifications to `src/Modules/ConfigOptions.lua`
**Purpose**: Add MCP configuration options

```lua
-- Add to config options:
{ var = "mcpEnabled", type = "check", label = "Enable MCP Bridge", tooltip = "Allow external tools (like AI assistants) to control Path of Building" },
{ var = "mcpPort", type = "number", label = "MCP Bridge Port", tooltip = "TCP port for MCP communication (default: 49085)", defaultValue = 49085 },
```

---

### Part 2: New MCP Tools to Create in poe2-mcp

#### 2.1 PoB Connection Tools

```python
# src/pob/pob_client.py

import socket
import json
from typing import Optional, Dict, Any

class PoBClient:
    """Client for communicating with Path of Building's MCP Bridge."""

    def __init__(self, host: str = "localhost", port: int = 49085, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._request_id = 0

    def _send_command(self, method: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Send a JSON-RPC command to PoB."""
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or {}
        }

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
            sock.sendall((json.dumps(request) + "\n").encode())

            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b"\n" in response:
                    break

            return json.loads(response.decode())

    def ping(self) -> Dict[str, Any]:
        """Check if PoB is running and responsive."""
        return self._send_command("ping")

    def get_build(self, format: str = "xml") -> Dict[str, Any]:
        """Get current build from PoB."""
        return self._send_command("get_build", {"format": format})

    def load_build(self, xml: Optional[str] = None, code: Optional[str] = None, name: str = "MCP Build") -> Dict[str, Any]:
        """Load a build into PoB."""
        params = {"name": name}
        if xml:
            params["xml"] = xml
        elif code:
            params["code"] = code
        return self._send_command("load_build", params)

    def get_calcs(self) -> Dict[str, Any]:
        """Get calculation results from PoB."""
        return self._send_command("get_calcs")

    def set_skill_group(self, skills: str, replace: bool = False) -> Dict[str, Any]:
        """Set skill group in PoB."""
        return self._send_command("set_skill_group", {"skills": skills, "replace": replace})

    def set_custom_mods(self, mods: str) -> Dict[str, Any]:
        """Set custom modifiers in PoB."""
        return self._send_command("set_custom_mods", {"mods": mods})

    def get_passive_tree(self) -> Dict[str, Any]:
        """Get allocated passive nodes from PoB."""
        return self._send_command("get_passive_tree")

    def set_passive_node(self, node_id: int, allocate: bool = True) -> Dict[str, Any]:
        """Allocate or deallocate a passive node."""
        return self._send_command("set_passive_node", {"nodeId": node_id, "allocate": allocate})

    def get_items(self) -> Dict[str, Any]:
        """Get equipped items from PoB."""
        return self._send_command("get_items")

    def compare_builds(self, xml: Optional[str] = None, code: Optional[str] = None) -> Dict[str, Any]:
        """Compare current build with another."""
        params = {}
        if xml:
            params["xml"] = xml
        elif code:
            params["code"] = code
        return self._send_command("compare_builds", params)
```

#### 2.2 New MCP Tool Definitions

Add these tools to `src/mcp_server.py`:

```python
# Tool: pob_connect
async def _handle_pob_connect(self, args: dict) -> List[types.TextContent]:
    """Connect to Path of Building instance."""
    try:
        from src.pob.pob_client import PoBClient

        host = args.get("host", "localhost")
        port = args.get("port", 49085)

        client = PoBClient(host=host, port=port)
        result = client.ping()

        if result.get("result", {}).get("status") == "ok":
            self.pob_client = client
            return [types.TextContent(
                type="text",
                text=f"Connected to Path of Building v{result['result'].get('version', 'unknown')}"
            )]
        else:
            return [types.TextContent(
                type="text",
                text=f"Connection failed: {result.get('error', {}).get('message', 'Unknown error')}"
            )]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]

# Tool: pob_push_build
async def _handle_pob_push_build(self, args: dict) -> List[types.TextContent]:
    """Push a build to Path of Building."""
    try:
        if not hasattr(self, 'pob_client'):
            return [types.TextContent(type="text", text="Not connected to PoB. Use pob_connect first.")]

        # Generate XML from character data or use provided
        xml = args.get("xml")
        code = args.get("code")
        name = args.get("name", "MCP Generated Build")

        if not xml and not code:
            # Try to get from current character context
            account = args.get("account")
            character = args.get("character")
            if account and character:
                # Fetch and convert character to PoB XML
                char_data = await self._fetch_character(account, character)
                xml = self._convert_to_pob_xml(char_data)

        result = self.pob_client.load_build(xml=xml, code=code, name=name)

        if result.get("result", {}).get("success"):
            return [types.TextContent(type="text", text=f"Build '{name}' loaded in Path of Building")]
        else:
            return [types.TextContent(type="text", text=f"Failed to load build: {result}")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]

# Tool: pob_pull_calcs
async def _handle_pob_pull_calcs(self, args: dict) -> List[types.TextContent]:
    """Pull calculation results from Path of Building."""
    try:
        if not hasattr(self, 'pob_client'):
            return [types.TextContent(type="text", text="Not connected to PoB. Use pob_connect first.")]

        result = self.pob_client.get_calcs()

        if "result" in result:
            calcs = result["result"]
            summary = self._format_calcs_summary(calcs)
            return [types.TextContent(type="text", text=summary)]
        else:
            return [types.TextContent(type="text", text=f"Failed to get calcs: {result}")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]

# Tool: pob_compare
async def _handle_pob_compare(self, args: dict) -> List[types.TextContent]:
    """Compare current PoB build with another."""
    try:
        if not hasattr(self, 'pob_client'):
            return [types.TextContent(type="text", text="Not connected to PoB. Use pob_connect first.")]

        code = args.get("code")
        xml = args.get("xml")

        result = self.pob_client.compare_builds(xml=xml, code=code)

        if "result" in result:
            comparison = result["result"]["comparison"]
            summary = self._format_comparison_summary(comparison)
            return [types.TextContent(type="text", text=summary)]
        else:
            return [types.TextContent(type="text", text=f"Comparison failed: {result}")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]

# Tool: pob_suggest_change
async def _handle_pob_suggest_change(self, args: dict) -> List[types.TextContent]:
    """Suggest and preview a change in PoB."""
    try:
        if not hasattr(self, 'pob_client'):
            return [types.TextContent(type="text", text="Not connected to PoB. Use pob_connect first.")]

        change_type = args.get("type")  # "skill", "passive", "item", "config"

        # Get current state
        before = self.pob_client.get_calcs()["result"]

        # Apply change based on type
        if change_type == "skill":
            self.pob_client.set_skill_group(args["skills"], args.get("replace", False))
        elif change_type == "passive":
            self.pob_client.set_passive_node(args["node_id"], args.get("allocate", True))
        elif change_type == "config":
            self.pob_client.set_custom_mods(args.get("mods", ""))

        # Get new state
        after = self.pob_client.get_calcs()["result"]

        # Format difference
        diff = self._calculate_stat_diff(before, after)
        return [types.TextContent(type="text", text=diff)]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]
```

#### 2.3 Complete Tool List for PoB Integration

| Tool Name | Direction | Description |
|-----------|-----------|-------------|
| `pob_connect` | MCP→PoB | Establish connection to running PoB instance |
| `pob_disconnect` | MCP→PoB | Close connection to PoB |
| `pob_status` | MCP→PoB | Check PoB connection status and build state |
| `pob_push_build` | MCP→PoB | Send build data to PoB for visualization |
| `pob_push_character` | MCP→PoB | Send poe.ninja character to PoB |
| `pob_pull_build` | PoB→MCP | Get current build from PoB |
| `pob_pull_calcs` | PoB→MCP | Get calculation results from PoB |
| `pob_pull_tree` | PoB→MCP | Get passive tree allocation from PoB |
| `pob_pull_items` | PoB→MCP | Get equipped items from PoB |
| `pob_compare` | Bidirectional | Compare builds with PoB's calculation engine |
| `pob_suggest_skill` | MCP→PoB | Suggest skill changes and preview impact |
| `pob_suggest_passive` | MCP→PoB | Suggest passive node changes and preview impact |
| `pob_suggest_item` | MCP→PoB | Suggest item changes and preview impact |
| `pob_optimize` | MCP→PoB | Run optimization with PoB validation |
| `pob_validate` | MCP→PoB | Validate build using PoB's calculation engine |

---

### Part 3: XML Build Format Specification

#### 3.1 Complete XML Structure

```xml
<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
    <Build
        targetVersion="0_3"
        level="85"
        className="Warrior"
        ascendClassName="Titan"
        mainSocketGroup="1"
        viewMode="TREE"
    />

    <Import importLink="https://poe.ninja/poe2/builds/..." />

    <Spec
        nodes="123,456,789,..."
        classId="0"
        ascendClassId="1"
        treeVersion="0_3"
    >
        <Sockets>
            <Socket nodeId="12345" itemId="3" />
        </Sockets>
        <Overrides>
            <!-- Passive node overrides -->
        </Overrides>
    </Spec>

    <Tree>
        <Spec title="Main" nodes="..." classId="0" ascendClassId="1" />
        <Spec title="Alt Spec" nodes="..." classId="0" ascendClassId="1" />
    </Tree>

    <Notes>
        User notes and build description go here.
    </Notes>

    <Items activeItemSet="1">
        <Item id="1">
            Rarity: RARE
            Exquisite Blade
            Titanium Spirit Shield
            LevelReq: 62
            Implicits: 1
            +25% to Elemental Resistances
            +120 to maximum Life
            +45% to Fire Resistance
            +38% to Cold Resistance
        </Item>
        <ItemSet id="1" title="Default">
            <Slot name="Weapon 1" itemId="1" />
            <Slot name="Weapon 2" itemId="2" />
            <Slot name="Helmet" itemId="3" />
            <Slot name="Body Armour" itemId="4" />
            <Slot name="Gloves" itemId="5" />
            <Slot name="Boots" itemId="6" />
            <Slot name="Amulet" itemId="7" />
            <Slot name="Ring 1" itemId="8" />
            <Slot name="Ring 2" itemId="9" />
            <Slot name="Belt" itemId="10" />
        </ItemSet>
    </Items>

    <Skills activeSkillSet="1" defaultGemLevel="20" defaultGemQuality="0">
        <SkillSet id="1" title="Default">
            <Skill
                slot="Weapon 1"
                label=""
                mainActiveSkill="1"
                enabled="true"
            >
                <Gem
                    nameSpec="Earthquake"
                    level="20"
                    quality="0"
                    qualityId="Default"
                    enabled="true"
                    skillId="earthquake"
                />
                <Gem
                    nameSpec="Melee Physical Damage Support"
                    level="20"
                    quality="0"
                    enabled="true"
                    skillId="support_melee_physical"
                />
            </Skill>
        </SkillSet>
    </Skills>

    <Config>
        <Input name="enemyIsBoss" string="Pinnacle" />
        <Input name="enemyPhysicalReduction" number="0" />
        <Input name="buffOnslaught" boolean="true" />
        <Input name="customMods" string="10% increased Damage" />
    </Config>
</PathOfBuilding2>
```

#### 3.2 Character Data to XML Conversion

```python
# src/pob/xml_generator.py

import xml.etree.ElementTree as ET
from typing import Dict, Any, List
import base64
import zlib

class PoBXMLGenerator:
    """Generate Path of Building XML from character data."""

    def __init__(self):
        self.class_ids = {
            "Warrior": 0, "Ranger": 1, "Witch": 2,
            "Duelist": 3, "Marauder": 4, "Shadow": 5, "Templar": 6
        }
        self.ascend_ids = {
            "Titan": 1, "Warbringer": 2,  # Warrior
            "Deadeye": 1, "Pathfinder": 2,  # Ranger
            # ... etc
        }

    def generate(self, character_data: Dict[str, Any]) -> str:
        """Generate PoB XML from character data."""
        root = ET.Element("PathOfBuilding2")

        # Build section
        build = ET.SubElement(root, "Build")
        build.set("targetVersion", "0_3")
        build.set("level", str(character_data.get("level", 1)))
        build.set("className", character_data.get("class", "Warrior"))
        build.set("ascendClassName", character_data.get("ascendancy", ""))

        # Spec section (passive tree)
        if "passives" in character_data:
            self._add_spec(root, character_data)

        # Items section
        if "equipment" in character_data:
            self._add_items(root, character_data)

        # Skills section
        if "skills" in character_data:
            self._add_skills(root, character_data)

        # Config section
        self._add_config(root, character_data)

        # Notes section
        notes = ET.SubElement(root, "Notes")
        notes.text = f"Generated from poe2-mcp\nAccount: {character_data.get('account', 'Unknown')}\nCharacter: {character_data.get('name', 'Unknown')}"

        return ET.tostring(root, encoding="unicode")

    def _add_spec(self, root: ET.Element, data: Dict[str, Any]):
        """Add passive tree specification."""
        spec = ET.SubElement(root, "Spec")

        passives = data.get("passives", {})
        nodes = passives.get("nodes", [])

        spec.set("nodes", ",".join(str(n) for n in nodes))
        spec.set("classId", str(self.class_ids.get(data.get("class", "Warrior"), 0)))
        spec.set("ascendClassId", str(self.ascend_ids.get(data.get("ascendancy", ""), 0)))
        spec.set("treeVersion", "0_3")

    def _add_items(self, root: ET.Element, data: Dict[str, Any]):
        """Add items section."""
        items_elem = ET.SubElement(root, "Items")
        items_elem.set("activeItemSet", "1")

        equipment = data.get("equipment", [])
        item_set = ET.SubElement(items_elem, "ItemSet")
        item_set.set("id", "1")
        item_set.set("title", "Default")

        for idx, item in enumerate(equipment, 1):
            # Create Item element
            item_elem = ET.SubElement(items_elem, "Item")
            item_elem.set("id", str(idx))
            item_elem.text = self._format_item_text(item)

            # Create Slot reference
            slot = ET.SubElement(item_set, "Slot")
            slot.set("name", item.get("slot", f"Slot {idx}"))
            slot.set("itemId", str(idx))

    def _format_item_text(self, item: Dict[str, Any]) -> str:
        """Format item data as PoB item text."""
        lines = []

        rarity = item.get("rarity", "RARE").upper()
        lines.append(f"Rarity: {rarity}")

        if item.get("name"):
            lines.append(item["name"])

        if item.get("base"):
            lines.append(item["base"])

        if item.get("level_req"):
            lines.append(f"LevelReq: {item['level_req']}")

        # Implicits
        implicits = item.get("implicits", [])
        if implicits:
            lines.append(f"Implicits: {len(implicits)}")
            lines.extend(implicits)

        # Explicits
        explicits = item.get("explicits", [])
        lines.extend(explicits)

        return "\n".join(lines)

    def _add_skills(self, root: ET.Element, data: Dict[str, Any]):
        """Add skills section."""
        skills_elem = ET.SubElement(root, "Skills")
        skills_elem.set("activeSkillSet", "1")
        skills_elem.set("defaultGemLevel", "20")
        skills_elem.set("defaultGemQuality", "0")

        skill_set = ET.SubElement(skills_elem, "SkillSet")
        skill_set.set("id", "1")
        skill_set.set("title", "Default")

        for skill_group in data.get("skills", []):
            skill = ET.SubElement(skill_set, "Skill")
            skill.set("slot", skill_group.get("slot", ""))
            skill.set("enabled", "true")
            skill.set("mainActiveSkill", "1")

            for gem_data in skill_group.get("gems", []):
                gem = ET.SubElement(skill, "Gem")
                gem.set("nameSpec", gem_data.get("name", ""))
                gem.set("level", str(gem_data.get("level", 20)))
                gem.set("quality", str(gem_data.get("quality", 0)))
                gem.set("enabled", "true")

    def _add_config(self, root: ET.Element, data: Dict[str, Any]):
        """Add config section."""
        config = ET.SubElement(root, "Config")

        config_data = data.get("config", {})

        for key, value in config_data.items():
            input_elem = ET.SubElement(config, "Input")
            input_elem.set("name", key)

            if isinstance(value, bool):
                input_elem.set("boolean", str(value).lower())
            elif isinstance(value, (int, float)):
                input_elem.set("number", str(value))
            else:
                input_elem.set("string", str(value))

    def to_pob_code(self, xml_text: str) -> str:
        """Convert XML to PoB share code."""
        compressed = zlib.compress(xml_text.encode('utf-8'), 9)
        encoded = base64.b64encode(compressed).decode('ascii')
        # PoB uses URL-safe base64
        return encoded.replace('+', '-').replace('/', '_')

    def from_pob_code(self, code: str) -> str:
        """Convert PoB share code to XML."""
        # Reverse URL-safe base64
        encoded = code.replace('-', '+').replace('_', '/')
        compressed = base64.b64decode(encoded)
        return zlib.decompress(compressed).decode('utf-8')
```

---

### Part 4: Implementation Phases

#### Phase 1: XML Generation (2-3 days)
**Deliverables:**
- `src/pob/xml_generator.py` - Generate PoB XML from character data
- `src/pob/xml_parser.py` - Parse PoB XML into structured data
- Enhanced `export_pob` MCP tool using new generator
- Unit tests for XML generation/parsing

**Tasks:**
1. Implement `PoBXMLGenerator` class
2. Implement `PoBXMLParser` class
3. Add PoB code encoding/decoding
4. Test with real character data from poe.ninja
5. Verify generated XML opens correctly in PoB

#### Phase 2: File-Based Sync (2-3 days)
**Deliverables:**
- `save_to_pob` tool - Save builds to PoB builds folder
- Build naming and organization conventions
- File watcher for detecting PoB changes (optional)

**Tasks:**
1. Detect PoB installation path
2. Create `MCP_Synced` subfolder in PoB builds
3. Implement save/load with proper file naming
4. Add timestamp and version tracking
5. Test manual workflow (MCP saves, user opens PoB)

#### Phase 3: Socket Communication (3-5 days)
**Deliverables:**
- PoB-side: `MCPBridge.lua`, `MCPCommands.lua`, `MCPInit.lua`
- MCP-side: `pob_client.py`
- Connection management tools

**Tasks:**
1. Implement PoB Lua modules
2. Modify PoB's `Main.lua` for MCP integration
3. Implement Python client
4. Add reconnection and error handling
5. Test bidirectional communication

#### Phase 4: Real-Time Integration (3-5 days)
**Deliverables:**
- Full suite of PoB MCP tools (15 tools)
- Live calculation sync
- Build comparison features

**Tasks:**
1. Implement all command handlers in PoB
2. Implement all MCP tools
3. Add calculation result formatting
4. Add comparison and diff display
5. Integration testing

#### Phase 5: Optimization Features (5-7 days)
**Deliverables:**
- AI-powered optimization with PoB validation
- Suggestion preview system
- Passive tree path finding

**Tasks:**
1. Implement `pob_suggest_*` tools
2. Add optimization with PoB verification
3. Implement passive tree navigation
4. Add item upgrade suggestions
5. End-to-end testing

---

### Part 5: File Summary

#### Files to CREATE in Path of Building:
```
src/Modules/MCPBridge.lua      - Core IPC module (~150 lines)
src/Modules/MCPCommands.lua    - Command handlers (~250 lines)
src/Modules/MCPInit.lua        - Initialization (~40 lines)
```

#### Files to MODIFY in Path of Building:
```
src/Modules/Main.lua           - Add MCP init and poll calls
src/Modules/ConfigOptions.lua  - Add MCP enable/port settings
```

#### Files to CREATE in poe2-mcp:
```
src/pob/__init__.py           - Module init
src/pob/pob_client.py         - PoB TCP client (~200 lines)
src/pob/xml_generator.py      - XML generation (~300 lines)
src/pob/xml_parser.py         - XML parsing (~200 lines)
docs/POB_INTEGRATION_PLAN.md  - This document
tests/test_pob_integration.py - Integration tests
```

#### Files to MODIFY in poe2-mcp:
```
src/mcp_server.py             - Add PoB tools registration/handlers
```

---

### Part 6: Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| PoB updates break integration | Medium | High | Pin to specific PoB version, monitor releases |
| Socket conflicts with other tools | Low | Medium | Make port configurable, use fallback ports |
| Performance impact on PoB | Low | Medium | Non-blocking I/O, poll timeout limits |
| Security concerns (open socket) | Medium | Medium | Bind to localhost only, optional auth |
| PoB fork diverges from upstream | Medium | Low | Track upstream changes, maintain compatibility |

---

### Part 7: Success Criteria

**Phase 1 Complete:**
- [ ] Can generate valid PoB XML from any poe.ninja character
- [ ] Generated XML opens in PoB without errors
- [ ] PoB code export/import works correctly

**Phase 2 Complete:**
- [ ] Builds save to correct PoB folder
- [ ] User can manually open MCP-generated builds in PoB
- [ ] Build organization is intuitive

**Phase 3 Complete:**
- [ ] MCP can connect to running PoB instance
- [ ] Bidirectional communication works
- [ ] Connection survives PoB restarts gracefully

**Phase 4 Complete:**
- [ ] All 15 PoB tools functional
- [ ] Real-time calculation sync works
- [ ] Build comparison shows meaningful diffs

**Phase 5 Complete:**
- [ ] AI suggestions reflect in PoB in real-time
- [ ] User can accept/reject suggestions
- [ ] Full optimization loop works end-to-end

---

## Conclusion

This integration transforms the MCP from a command-line analysis tool into a full visual planning assistant. Users can:

1. Analyze characters with AI intelligence
2. See builds visualized in Path of Building
3. Get AI suggestions with real-time preview
4. Compare builds using PoB's calculation engine
5. Collaborate between AI analysis and manual planning

The architecture is designed for stability, extensibility, and minimal intrusion into the PoB codebase. The socket-based approach allows the integration to be optional and easily disabled.

---

**Document Version:** 1.0
**Last Updated:** 2026-01-28
**Author:** HivemindMinion (Claude Code Operative)

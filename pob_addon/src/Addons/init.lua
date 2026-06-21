-- MCP Bridge Addon Loader for Path of Building (PoE2)
-- https://github.com/HivemindOverlord/poe2-mcp
--
-- This file is loaded by Launch.lua and initializes the MCP Bridge addon.
-- The bridge allows external tools (like AI assistants) to communicate with PoB.

local function loadAddon()
    local scriptPath = GetScriptPath()
    local addonPath = scriptPath .. "/Addons/MCPBridge"

    -- Check if addon exists
    local testFile = io.open(addonPath .. "/bridge.lua", "r")
    if not testFile then
        ConPrintf("[MCP Addon] MCPBridge not found at: %s", addonPath)
        return
    end
    testFile:close()

    -- Load the bridge module
    local success, err = pcall(function()
        dofile(addonPath .. "/bridge.lua")
    end)

    if success then
        ConPrintf("[MCP Addon] MCPBridge loaded successfully")
    else
        ConPrintf("[MCP Addon] Failed to load MCPBridge: %s", tostring(err))
    end
end

-- Only load if not in headless mode (HeadlessWrapper sets specific globals)
if RenderInit then
    loadAddon()
end
